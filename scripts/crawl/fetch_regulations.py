"""抓取监管法规全文，结构化为法规 JSON 草稿（知识库数据飞轮第一步）。

与 fetch_penalty_cases.py 同族：官方公开渠道、可溯源、限速抓取、失败跳过不中断。
三个源（全部经真实探测确认可用，2026-08）：
- 国务院政策文件库  检索 API（sousuo.www.gov.cn/search-gov/data）+ 详情页
  静态 HTML 全文（#UCAP-CONTENT），覆盖国务院文件与部委规范性文件（资管新规类）
- 金监总局规章库    JSON 列表（SelectDocByItemUUIdsAndChild）+ 详情 docClob
  （Word 导出的全文 HTML，个别仅附件，走 attachment 下载兜底）
- 证监会规章库      静态列表页（c106256/fg.shtml）+ 详情页正文/附件

国家法律法规数据库（flk.npc.gov.cn）已改版为纯前端 SPA、检索 API 不可达，
法律类全文走人工兜底（scripts/init_data/review_regulations.py 同一确认入口）。

设计：watchlist 驱动——scripts/crawl/regulation_watchlist.json 列出目标法规，
逐条在三个源里按标题模糊匹配取全文；条款切分优先确定性（第X章/节/条锚点），
失败（无锚点/条号断序）才回退 LLM 结构化，控制成本。产出写入
scripts/init_data/pending/regulations/，经 review_regulations.py 人工确认后
合并进 regulations_crawled.json，再走既有导入链路（import_regulations --json）。

用法（仓库根目录，需 DASHSCOPE_API_KEY 才启用 LLM 兜底）:
    python scripts/crawl/fetch_regulations.py [--targets 法规名1,法规名2]
        [--max-nfra-pages 10] [--dry-run] [--out-dir scripts/init_data/pending/regulations]
"""

import argparse
import json
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Windows 默认控制台代码页是 GBK，print 中文案会 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_PATH = Path(__file__).resolve().parent / "regulation_watchlist.json"
DEFAULT_OUT_DIR = _ROOT / "scripts" / "init_data" / "pending" / "regulations"

GOVCN_SEARCH = "https://sousuo.www.gov.cn/search-gov/data"
GOVCN_TYPES = ["zhengcelibrary_bm", "zhengcelibrary_gw"]  # 部委文件 / 国务院文件
NFRA_LIST = (
    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
    "?itemId=928&pageIndex={page}&pageSize=50"
)
NFRA_DETAIL = "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectByDocId?docId={doc_id}"
CSRC_LIST = "https://www.csrc.gov.cn/csrc/c106256/fg.shtml"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 20
_PAUSE = 0.5

_VALID_DOMAINS = {"banking", "fund", "insurance", "wealth", "consumer", "advertising"}

# ---------- 条款锚点 ----------
_CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
# 条锚点：行首"第X条"（可带"之一"修正案后缀）；正文内"本法第X条"这类引用不在行首，天然排除
_ANCHOR_RE = re.compile(
    r"^第([零〇一二三四五六七八九十百千\d]{1,12})条(之[一二三四五六七八九十]+)?\s*(.*)$"
)
_CHAPTER_RE = re.compile(r"^第([零〇一二三四五六七八九十百千\d]{1,10})章\s*(.*)$")
_SECTION_RE = re.compile(r"^第([零〇一二三四五六七八九十百千\d]{1,10})节\s*(.*)$")
# 顿号锚点：指导意见类文件用"一、二、三"编号无"第X条"结构（现有库把"二、"映射为"第二条"）
_DUNHAO_RE = re.compile(r"^([零〇一二三四五六七八九十百千\d]{1,10})、\s*(.*)$")
# 目录行：只有条号没有正文（"第三条 …… 5"），必须跳过防止污染切分
_TOC_RE = re.compile(
    r"^(?:第[零〇一二三四五六七八九十百千\d]{1,12}条|[一二三四五六七八九十]{1,10}、)"
    r"[\s.．…··—\-]*\d{0,4}\s*$"
)


def _get(url: str, retries: int = 2) -> httpx.Response:
    """限速抓取；瞬时网络抖动/限流做指数退避重试，避免单次失败中断全流程。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)
            resp.raise_for_status()
            time.sleep(_PAUSE)
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < retries:
                wait = 2**attempt
                print(f"  ! 请求失败({type(exc).__name__})，{wait}s 后重试: {url[:80]}")
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def _clean(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()


def _squeeze_cjk(text: str) -> str:
    """去掉汉字之间的空白（HTML 渲染残留，如"记录 和 保存"→"记录和保存"）。"""
    return re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", text or "")


# ---------- 标题模糊匹配 ----------

def _norm_title(title: str) -> str:
    """标题归一：去书名号/空白/标点，便于《通知》标题与法规名对齐。"""
    t = re.sub(r"[《》\s（）()【】、，,。.:：;；\"'“”]", "", title or "")
    return t.lower()


def _safe_filename(name: str) -> str:
    """Windows 文件名非法字符（<>:"/\\|?*）替换为下划线，防止写盘 PermissionError。"""
    return re.sub(r'[<>:"/\\|?*]', "_", name or "")


def title_score(watch: str, candidate: str) -> float:
    """标题相似度 0-1：归一化后双向包含给高分，否则按字符 bigram Jaccard。"""
    a, b = _norm_title(watch), _norm_title(candidate)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92  # 包含关系（如 watch 是简称或候选带发文机关前缀）
    ga = {a[i : i + 2] for i in range(len(a) - 1)}
    gb = {b[i : i + 2] for i in range(len(b) - 1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def pick_best(watch: str, candidates: list[dict], threshold: float = 0.75) -> dict | None:
    """从候选里挑标题最接近的一条；低于阈值视为未命中（宁缺毋滥，防抓错法规）。"""
    best, best_score = None, 0.0
    for cand in candidates:
        score = title_score(watch, cand["title"])
        if score > best_score:
            best, best_score = cand, score
    if best is None or best_score < threshold:
        return None
    best["match_score"] = round(best_score, 3)
    return best


# ---------- 中文数字 ----------

def cn_to_int(text: str) -> int | None:
    """中文数字转 int（支持 一/十二/二十三/一百零五/纯阿拉伯）；解析失败返回 None。"""
    s = (text or "").strip()
    if s.isdigit():
        return int(s)
    if not s or any(ch not in _CN_NUM and ch not in "十百千" for ch in s):
        return None
    total, segment, num = 0, 0, 0  # total: 万以下累计, segment: 当前百/十段
    for ch in s:
        if ch in _CN_NUM:
            num = _CN_NUM[ch]
        elif ch == "十":
            segment += (num or 1) * 10
            num = 0
        elif ch == "百":
            segment += (num or 1) * 100
            num = 0
        elif ch == "千":
            segment += (num or 1) * 1000
            num = 0
    total = segment + num
    return total or None


# ---------- 条款切分（确定性优先） ----------


def extract_articles(text: str) -> list[dict]:
    """按 第X章/节/条 锚点确定性切分条款；返回与 regulations.json schema 对齐的 articles。

    - 条锚点必须行首：正文里"依照本法第X条"这类引用天然排除
    - 全文没有"第X条"结构时降级为顿号模式（"一、"编号 → 第二条 式条号，
      与现有 regulations.json 对资管新规的表示约定一致）
    - chapter_no 沿用现有数据约定：节标题并入章号字符串（"第三章 … 第二节 销售管理"）
    - content 以条号开头（与现有数据一致），条款内部行拼接为连贯文本
    """
    lines = [_squeeze_cjk(ln.strip()) for ln in text.split("\n") if ln.strip()]
    lines = [ln for ln in lines if not _TOC_RE.match(ln)]
    has_article_anchors = any(_ANCHOR_RE.match(ln) for ln in lines)
    chapter, articles = "", []
    for line in lines:
        m_ch, m_sec = _CHAPTER_RE.match(line), _SECTION_RE.match(line)
        if m_ch:
            chapter = f"第{m_ch.group(1)}章 {m_ch.group(2)}".strip()
            continue
        if m_sec:
            chapter = f"{chapter.split(' 第')[0]} 第{m_sec.group(1)}节 {m_sec.group(2)}".strip()
            continue
        m = _ANCHOR_RE.match(line) if has_article_anchors else None
        if m:
            articles.append(
                {
                    "chapter_no": chapter,
                    "article_no": f"第{m.group(1)}条",
                    "content": _clean(line),
                }
            )
            continue
        m = _DUNHAO_RE.match(line) if not has_article_anchors else None
        if m:
            articles.append(
                {
                    "chapter_no": chapter,
                    "article_no": f"第{m.group(1)}条",
                    "content": _clean(line),
                }
            )
            continue
        if articles and len(articles[-1]["content"]) < 4000:
            articles[-1]["content"] = _clean(articles[-1]["content"] + line)
    return articles


def numbering_quality(articles: list[dict]) -> float:
    """条号连续性 0-1：合法条号应从第一条起单调递增；用于判定是否需要 LLM 兜底。"""
    nums = [cn_to_int(a["article_no"][1:-1]) for a in articles]
    if not nums or nums[0] != 1:
        return 0.0
    increasing, missing = True, 0
    for prev, cur in zip(nums, nums[1:], strict=False):
        if prev is None or cur is None or cur <= prev:
            increasing = False
            break
        missing += cur - prev - 1
    if not increasing:
        return 0.0
    return 1.0 if missing == 0 else max(0.0, 1.0 - missing / len(articles))


def llm_structurize(llm, text: str) -> list[dict]:
    """确定性切分失败时按片调用 LLM 重切条款（逐字保留原文，禁止改写）。"""
    system = (
        "你是法规文本结构化助手。把给定的法规文本片段拆成条款，只输出 JSON 数组，"
        "不要输出任何其他文字："
        '[{"article_no": "第一条", "chapter_no": "第一章 总则", "content": "条款全文"}]。'
        "规则：content 必须逐字保留原文并以条号开头，不得改写增删；"
        "chapter_no 按最近出现的章/节标题填写（'第三章 x 第y节 z'），无法判断为空串；"
        "片段开头残缺的半个条款直接丢弃；片段结尾不完整的条款只输出完整部分。"
    )
    articles: list[dict] = []
    seen: set[str] = set()
    step = 2500
    for start in range(0, len(text), step):
        chunk = text[start : start + step]
        if len(chunk.strip()) < 50:
            continue
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": chunk + "\n\n请输出条款 JSON 数组："},
                ]
            )
        except Exception as exc:  # LLM 失败降级：跳过该片，不中断全流程
            print(f"  ! LLM 结构化失败，跳过 {len(chunk)} 字符: {type(exc).__name__}")
            continue
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        if not m:
            continue
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            no = str(it.get("article_no") or "").strip()
            content = _clean(str(it.get("content") or ""))
            if not no.startswith("第") or len(content) < 15 or content[:8] in seen:
                continue
            seen.add(content[:8])
            articles.append(
                {
                    "chapter_no": _clean(str(it.get("chapter_no") or "")),
                    "article_no": no,
                    "content": content,
                }
            )
    return articles


def text_to_articles(text: str, llm=None) -> tuple[list[dict], str]:
    """文本 → 条款列表。确定性优先，质量不达标且 LLM 可用时回退 LLM 重切。

    返回 (articles, method)。"""
    articles = extract_articles(text)
    if len(articles) >= 5 and numbering_quality(articles) >= 0.9:
        return articles, "deterministic"
    if llm is not None:
        retry = llm_structurize(llm, text)
        if len(retry) > len(articles):
            return retry, "llm"
    return articles, "deterministic"


# ---------- 三个数据源 ----------

def govcn_search(query: str) -> list[dict]:
    """国务院政策文件库标题检索（部委文件 + 国务院文件两类），返回标题/URL/发布机关候选。"""
    out: list[dict] = []
    for t in GOVCN_TYPES:
        try:
            resp = httpx.get(
                GOVCN_SEARCH,
                params={
                    "t": t,
                    "q": query,
                    "timetype": "timeqb",
                    "sort": "score",
                    "searchfield": "title",  # 标题字段精确检索；全文检索相关性差不可用
                    "p": 1,
                    "n": 10,
                },
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers=_HEADERS,
            )
            resp.raise_for_status()
            time.sleep(_PAUSE)
        except httpx.HTTPError as exc:
            print(f"  ! govcn 检索失败({t}): {type(exc).__name__}")
            continue
        items = (resp.json().get("searchVO") or {}).get("listVO") or []
        for it in items:
            if isinstance(it, dict) and it.get("title") and it.get("url"):
                title = re.sub(r"</?em>", "", _clean(it["title"]))  # 命中高亮 <em> 标签
                out.append(
                    {
                        "title": title,
                        "url": it["url"],
                        "puborg": _clean(it.get("puborg") or ""),
                        "pubtime": it.get("pubtime"),
                    }
                )
    return out


def govcn_fetch(url: str) -> tuple[str, str | None]:
    """抓详情页全文；返回 (正文, 文号)。文号从正文里识别（国办发〔2023〕25号 等）。

    注意用 html.parser 而非 lxml：gov.cn 部分页面标记畸形，lxml 建树后
    正文 div 会整个丢失（实测 content_7066927 等 2026 新页面）。"""
    resp = _get(url)
    resp.encoding = resp.charset_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    node = soup.select_one("#UCAP-CONTENT .trs_editor_view") or soup.select_one(
        "#UCAP-CONTENT"
    )
    text = node.get_text("\n", strip=True) if node else ""
    m = re.search(r"[^\s]{2,20}[〔\[]\d{4}[〕\]]\s*\d+\s*号", text[:2000])
    doc_no = _clean(m.group(0)) if m else None
    return text, doc_no


def nfra_list_items(max_pages: int) -> list[dict]:
    """金监总局规章库列表（政策规章规范性文件栏目 itemId=928），翻页收集。

    注意：SelectDocByItemUUIdsAndChild 系接口翻页到第 4 页会循环回第 1 页，
    只有 SelectDocByItemIdAndChild 系接口（与罚单爬虫同族）支持真实分页。"""
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            resp = _get(NFRA_LIST.format(page=page))
            rows = (resp.json().get("data") or {}).get("rows") or []
        except (httpx.HTTPError, ValueError) as exc:
            print(f"  ! nfra 列表第 {page} 页失败: {type(exc).__name__}")
            break
        if not rows:
            break
        for it in rows:
            title = _clean(it.get("docTitle") or it.get("title") or "")
            if it.get("docId") and title:
                items.append(
                    {
                        "doc_id": it["docId"],
                        "title": title,
                        "date": (it.get("publishDate") or "")[:10] or None,
                    }
                )
        print(f"  nfra 第 {page} 页: 累计 {len(items)} 条")
    return items


def _attachment_text(attachments) -> str:
    """附件兜底：下载 docx/pdf 并复用 src.parsers 解析（NFRA 部分规章只有附件）。"""
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        url = next(
            (att.get(k) for k in ("fileUrl", "docFileUrl", "pdfFileUrl", "url", "path")
             if att.get(k)),
            None,
        )
        if not url or not isinstance(url, str) or not url.startswith("http"):
            continue
        suffix = Path(url).suffix or ".pdf"
        try:
            resp = _get(url)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(resp.content)
                tmp = f.name
            from src.parsers import parse_document

            text = parse_document(tmp).text
            Path(tmp).unlink(missing_ok=True)
            if len(text.strip()) > 300:
                print(f"  + 附件兜底解析成功: {Path(url).name[:60]} ({len(text)} 字)")
                return text
        except Exception as exc:
            print(f"  ! 附件解析失败 {Path(url).name[:50]}: {type(exc).__name__}")
    return ""


def _clob_text(clob: str) -> str:
    """Word 导出 HTML → 正文。

    坑：docClob 里每个词常被包成独立内联元素，`get_text("\\n")` 会把
    "第二条" 拆成 "第\\n二\\n条"，行首锚点全失效、条款切出 0 条。
    按 <p> 段落取文本再拼行，既保留段落边界又不碎词。
    """
    soup = BeautifulSoup(clob, "lxml")
    paras = [p.get_text("", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p]
    return "\n".join(paras) if paras else soup.get_text("\n", strip=True)


def nfra_fetch(doc_id: int) -> tuple[str, str | None]:
    """详情 docClob（Word 导出全文 HTML）为主，附件为兜底；返回 (正文, 文号)。"""
    data = (_get(NFRA_DETAIL.format(doc_id=doc_id)).json() or {}).get("data") or {}
    text = ""
    clob = data.get("docClob") or ""
    if clob:
        text = _clob_text(clob)
    if len(text.strip()) < 500:
        text = _attachment_text(data.get("attachmentInfoVOList")) or text
    return text, _clean(data.get("documentNo") or "") or None


def csrc_list_items() -> list[dict]:
    """证监会规章库列表页（表格结构：序号/标题/下载）；按行解析取标题。"""
    resp = _get(CSRC_LIST)
    resp.encoding = resp.charset_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    items: list[dict] = []
    seen_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        if not re.match(r"^/csrc/c106256/c\d+/content\.shtml$", a["href"]):
            continue
        if a["href"] in seen_urls:
            continue
        seen_urls.add(a["href"])
        row = a.find_parent("tr")
        title = _clean(row.get_text()) if row else _clean(a.find_parent(["li", "div"]).get_text())
        title = re.sub(r"序号|标题|下载|\d{4}-\d{2}-\d{2}|^\d+\s*", " ", title).strip()
        if title:
            items.append({"url": "https://www.csrc.gov.cn" + a["href"], "title": title[:80]})
    return items


def _docx_text(url: str) -> str:
    """下载 .docx 并取段落文本（CSRC 规章页提供"下载文字版"，比网页正文干净）。"""
    resp = _get(url)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(resp.content)
        tmp = f.name
    try:
        import docx  # python-docx

        doc = docx.Document(tmp)
        paras = [p.text.strip() for p in doc.paragraphs]
        return "\n".join(p for p in paras if p)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _csrc_web_text(soup) -> str:
    """网页正文兜底：取含"第X条"最密的块，剥掉页头噪声行。"""
    best, best_hits = None, -1
    for node in soup.find_all(["div", "td"]):
        t = node.get_text("\n", strip=True)
        hits = len(re.findall(r"第[一二三四五六七八九十百零〇0-9]+条", t))
        if hits > best_hits and len(t) > 500:
            best, best_hits = t, hits
    text = best or ""
    noise = ("中国证券监督管理委员会规章", "下载图片版", "下载文字版", "打印本页", "关闭窗口")
    lines = [ln for ln in text.split("\n") if ln.strip() and ln.strip() not in noise]
    return "\n".join(lines)


def csrc_fetch(url: str) -> tuple[str, str | None]:
    resp = _get(url)
    resp.encoding = resp.charset_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    text = ""
    # 1) 优先"下载文字版"（.docx/.doc）：段落边界干净，条款锚点可靠
    docx_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"\.(docx?|wps)$", href, re.IGNORECASE):
            continue
        if "文字版" in (a.get_text() or "") or docx_url is None:
            docx_url = urljoin(url, href)
            if "文字版" in (a.get_text() or ""):
                break
    if docx_url and docx_url.lower().endswith(".docx"):
        try:
            text = _docx_text(docx_url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! CSRC 文字版解析失败 {type(exc).__name__}: {docx_url[-40:]}")
            text = ""
    # 2) 网页正文兜底
    if len(text.strip()) < 500:
        text = _csrc_web_text(soup)
    # 文号：优先"证监会令第N号"（规章口径），避免被"2021年3月18日证监会令第182号"截断成半句
    m = re.search(r"证监会令第\s*\d+\s*号", text[:2000])
    if m:
        return text, _clean(m.group(0))
    m = re.search(r"[^\s]{2,20}[〔\[]\d{4}[〕\]]\s*\d+\s*号", text[:2000])
    return text, (_clean(m.group(0)) if m else None)


# ---------- 组装与校验 ----------

def build_regulation(entry: dict, text: str, doc_no: str | None, meta: dict) -> dict:
    """把抓取结果组装成 regulations.json schema 的单条记录（含 _meta 溯源信息）。"""
    issuer = meta.get("issuer") or entry.get("issuer") or ""
    no = doc_no or meta.get("document_no") or ""
    if not no:  # regulation_no 是导入幂等键，缺失时用稳定可溯源的合成值
        no = f"{meta['source'].upper()}-{meta['source_id']}"
    reg = {
        "domain": entry["domain"],
        "regulation_name": entry["regulation_name"],
        "regulation_no": no,
        "issuer": issuer,
        "publish_date": meta.get("date") or "",
        "effective_date": entry.get("effective_date") or meta.get("date") or "",
        "status": entry.get("status", "effective"),
        "articles": [],
        "_meta": meta,
    }
    return reg


def validate_regulation(reg: dict) -> list[str]:
    """schema 校验：返回问题清单（空 = 通过）。review CLI 与单测共用。"""
    problems: list[str] = []
    if reg.get("domain") not in _VALID_DOMAINS:
        problems.append(f"domain 非法: {reg.get('domain')}")
    if not reg.get("regulation_name"):
        problems.append("regulation_name 缺失")
    if not reg.get("regulation_no"):
        problems.append("regulation_no 缺失（导入幂等键）")
    for field in ("publish_date", "effective_date"):
        v = reg.get(field) or ""
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            problems.append(f"{field} 格式非 YYYY-MM-DD: {v}")
    articles = reg.get("articles") or []
    if len(articles) < 5:
        problems.append(f"条款过少({len(articles)})，疑似正文不完整")
    for i, a in enumerate(articles):
        if not a.get("article_no"):
            problems.append(f"条款[{i}] 缺 article_no")
            break
        if len(a.get("content") or "") < 15:
            problems.append(f"条款[{i}] 内容过短")
            break
    if articles and numbering_quality(articles) < 0.5:
        problems.append("条号断序严重，疑似切分错误")
    return problems


# ---------- 主流程 ----------

def _load_watchlist(path: Path | None = None) -> list[dict]:
    with (path or WATCHLIST_PATH).open(encoding="utf-8") as f:
        return json.load(f)


def _already_have(name: str, out_dir: Path) -> bool:
    if list(out_dir.glob("*.json")):
        for p in out_dir.glob("*.json"):
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("regulation_name") == name:
                    return True
            except (json.JSONDecodeError, OSError):
                continue
    crawled = _ROOT / "scripts" / "init_data" / "regulations_crawled.json"
    if crawled.exists():
        try:
            for reg in json.loads(crawled.read_text(encoding="utf-8")):
                if reg.get("regulation_name") == name:
                    return True
        except (json.JSONDecodeError, OSError):
            pass
    return False


def _match_score_text(entry: dict, item_title: str) -> float:
    if title_score(entry["regulation_name"], item_title) >= 0.75:
        return title_score(entry["regulation_name"], item_title)
    for alias in entry.get("aliases") or []:
        if title_score(alias, item_title) >= 0.75:
            return title_score(alias, item_title)
    return 0.0


def fetch_one(entry: dict, nfra_index: list[dict] | None, llm) -> dict | None:
    """单个 watchlist 目标：按 源优先级 检索 → 取全文 → 切条款 → 组装。

    返回带 articles 的记录，抓不到全文返回 None。"""
    name = entry["regulation_name"]
    # 1) 国务院政策文件库（标题检索，直接命中详情页）
    try:
        cands = govcn_search(name)
        hit = pick_best(name, cands)
        if hit:
            text, doc_no = govcn_fetch(hit["url"])
            if len(text) >= 500:
                meta = {
                    "source": "govcn",
                    "source_id": hit["url"].rsplit("/", 1)[-1],
                    "source_url": hit["url"],
                    "issuer": hit.get("puborg") or "",
                    "source_title": hit["title"],
                    "date": _millis_to_date(hit.get("pubtime")),
                    "fetched_at": date.today().isoformat(),
                }
                return _finish(entry, text, doc_no, meta, llm)
    except httpx.HTTPError as exc:
        print(f"  ! govcn 通道异常: {type(exc).__name__}")

    # 2) 金监总局规章库（列表标题匹配 → 详情 docClob/附件）
    if nfra_index:
        best, best_score = None, 0.0
        for item in nfra_index:
            s = _match_score_text(entry, item["title"])
            if s > best_score:
                best, best_score = item, s
        if best is not None and best_score >= 0.75:
            print(f"  nfra 命中({best_score:.2f}): {best['title'][:60]}")
            text, doc_no = nfra_fetch(best["doc_id"])
            if len(text) >= 500:
                meta = {
                    "source": "nfra",
                    "source_id": str(best["doc_id"]),
                    "source_url": NFRA_PAGE_URL.format(doc_id=best["doc_id"]),
                    "issuer": "国家金融监督管理总局",
                    "source_title": best["title"],
                    "date": best.get("date"),
                    "fetched_at": date.today().isoformat(),
                }
                return _finish(entry, text, doc_no, meta, llm)

    # 3) 证监会规章库
    try:
        cands = csrc_list_items()
        hit = pick_best(name, cands)
        if hit:
            text, doc_no = csrc_fetch(hit["url"])
            if len(text) >= 500:
                meta = {
                    "source": "csrc",
                    "source_id": hit["url"].rsplit("/", 1)[-1],
                    "source_url": hit["url"],
                    "issuer": "中国证券监督管理委员会",
                    "source_title": hit["title"],
                    "date": None,
                    "fetched_at": date.today().isoformat(),
                }
                return _finish(entry, text, doc_no, meta, llm)
    except httpx.HTTPError as exc:
        print(f"  ! csrc 通道异常: {type(exc).__name__}")
    return None


NFRA_PAGE_URL = "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={doc_id}&itemId=928"


def _millis_to_date(millis) -> str | None:
    try:
        if millis and int(millis) > 0:
            return date.fromtimestamp(int(millis) / 1000).isoformat()
    except (TypeError, ValueError, OSError):
        pass
    return None


def _derive_name(source_title: str) -> str | None:
    """从来源标题派生法规名：①《》内书名 ②从"关于"起的公文标题（去掉发文机关前缀）。

    防错标：模糊命中抓到别的文件时，regulation_name 必须以实际文件为准。"""
    m = re.search(r"《(.+?)》", source_title or "")
    if m:
        return m.group(1)
    m = re.search(r"关于.{4,}", source_title or "")
    if m:
        return _clean(m.group(0))
    return None


def _extract_doc_no(text: str, title: str) -> str | None:
    """文号兜底提取：优先 令第N号（规章，含带年份与不带年份两种形式），其次 〔YYYY〕N号。"""
    for source in (text[:1500], _norm_title(title)):
        m = re.search(
            r"[\u4e00-\u9fa5]{2,15}令\s*(?:20\d{2}年)?\s*[(（]?\s*第\s*\d{1,4}\s*号", source
        )
        if m:
            return re.sub(r"\s+", "", m.group(0))  # 正文里令号常跨行，压掉全部空白
    pattern = r"[^\s]{2,20}[〔\[]\d{4}[〕\]]\s*\d+\s*号"
    for source in (text[:2000], _norm_title(title)):
        m = re.search(pattern, source)
        if m:
            return _clean(m.group(0))
    return None


def _finish(
    entry: dict, text: str, doc_no: str | None, meta: dict, llm, min_articles: int = 5
) -> dict | None:
    articles, method = text_to_articles(text, llm)
    if len(articles) < min_articles:
        print(f"  ! 条款切分不足({len(articles)})，放弃: {entry['regulation_name']}")
        return None
    meta["extraction"] = method
    src_title = meta.get("source_title") or ""
    derived = _derive_name(src_title)
    if derived and _norm_title(derived) != _norm_title(entry["regulation_name"]):
        print(f"  实际文件名与目标不同，以实际为准: {derived}")
        entry = {**entry, "regulation_name": derived}
    doc_no = doc_no or _extract_doc_no(text, src_title)
    reg = build_regulation(entry, text, doc_no, meta)
    reg["articles"] = articles
    problems = validate_regulation(reg)
    reg["_meta"]["problems"] = problems
    return reg


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取监管法规全文，产出待确认 JSON 草稿")
    parser.add_argument("--targets", default="", help="仅抓取指定法规名（逗号分隔），默认全部")
    parser.add_argument("--max-nfra-pages", type=int, default=10, help="NFRA 规章库翻页数")
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR), help="草稿输出目录（pending）"
    )
    parser.add_argument(
        "--watchlist",
        default="",
        help="改用指定 watchlist 文件（默认 scripts/crawl/regulation_watchlist.json）",
    )
    parser.add_argument("--dry-run", action="store_true", help="不落盘，只打印抓取结果")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="禁用 LLM 结构化兜底（配额受限时用；切分质量不达标的条目会直接判未命中）",
    )
    args = parser.parse_args()

    from src.core.llm.client import get_llm

    llm = None if args.no_llm else get_llm()
    if args.no_llm:
        print("  --no-llm：仅确定性切分（不吃 LLM 配额）")
    elif llm is None:
        print("  未配置 DASHSCOPE_API_KEY：LLM 结构化兜底不可用，仅确定性切分")

    watchlist = _load_watchlist(Path(args.watchlist) if args.watchlist else None)
    targets = [t for t in args.targets.split(",") if t.strip()]
    if targets:
        watchlist = [w for w in watchlist if any(t in w["regulation_name"] for t in targets)]
    if not watchlist:
        print("watchlist 为空或无匹配目标")
        return

    print(f"== 目标 {len(watchlist)} 部法规，先建 NFRA 规章库索引 ==")
    nfra_index = nfra_list_items(args.max_nfra_pages)
    print(f"NFRA 索引 {len(nfra_index)} 条\n")

    out_dir = Path(args.out_dir)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    ok, empty = 0, []
    for entry in watchlist:
        name = entry["regulation_name"]
        if not args.dry_run and _already_have(name, out_dir):
            print(f"- 跳过（已有草稿/已采纳）: {name}")
            continue
        print(f"== 抓取: {name}")
        try:
            reg = fetch_one(entry, nfra_index, llm)
        except Exception as exc:  # 单目标失败不中断全流程
            print(f"  ! 目标异常: {type(exc).__name__}: {exc}")
            reg = None
        if reg is None:
            empty.append(name)
            continue
        ok += 1
        print(
            f"  + {len(reg['articles'])} 条款 / {reg['_meta']['extraction']} / "
            f"{reg['_meta']['source']} / 文号 {reg['regulation_no']}"
        )
        for p in reg["_meta"]["problems"]:
            print(f"    ! 校验: {p}")
        if not args.dry_run:
            stem = _safe_filename(_norm_title(reg["regulation_name"]))[:40]
            out = out_dir / f"{reg['domain']}-{stem}.json"
            out.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  → {out.name}")

    print(f"\n完成: 成功 {ok} 部, 未命中 {len(empty)} 部（走人工兜底）")
    for name in empty:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
