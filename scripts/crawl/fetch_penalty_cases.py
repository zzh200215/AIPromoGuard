"""抓取真实监管处罚数据，生成 penalty_cases.json（替换早期 AI 生成样例）。

数据源（监管机构官方公开渠道，均可溯源）：
- 国家金融监督管理总局各监管局"行政处罚信息公开表"
  列表: /cbircweb/DocInfo/SelectDocByItemIdAndChild?itemId=4114（JSON）
  详情: /cbircweb/DocInfo/SelectByDocId?docId=...（docClob 为 HTML 表格，
        每行一笔真实罚单：当事人/主要违法违规行为/行政处罚内容/作出决定机关）
- 中国证监会"行政处罚决定书"
  入口: 官网首页行政处罚挂件（静态链接，挂件附 MM-DD 日期）→ content.shtml
        正文，含文号〔20xx〕N号/当事人/违法事实/我会决定

产品合规相关罚单（销售/宣传/适当性/理财/保险/基金等）优先保留，
其余作为补充，总量 --max 控制。输出与 scripts/init_data/import_penalty_cases.py
兼容；每条附 source_url 供人工溯源（导入脚本按模型列白名单忽略该字段）。
related_regulations 由法规库名称关键词匹配自动关联（未命中留空，导入端告警）。

用法（仓库根目录）:
    python scripts/crawl/fetch_penalty_cases.py [--out scripts/init_data/penalty_cases.json]
        [--nfra-docs 6] [--csrc 6] [--max 32]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Windows 默认控制台代码页是 GBK，print 中文案会 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from bs4 import BeautifulSoup

NFRA_LIST = (
    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
    "?itemId=4114&pageIndex=1&pageSize=20"
)
NFRA_DETAIL = "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectByDocId?docId={doc_id}"
NFRA_PAGE = "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={doc_id}&itemId=4114"
CSRC_HOME = "https://www.csrc.gov.cn/"
CSRC_URL_RE = re.compile(r"^/csrc/c101928/c\d+/content\.shtml$")

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 20
_PAUSE = 0.5  # 抓取间隔，降低对源站压力

# 产品合规相关性（销售/宣传/适当性/产品线），命中者优先保留
_RELEVANT_RE = re.compile(
    r"销售|宣传|误导|适当性|理财|保险|基金|承诺|保本|收益|欺骗|隐瞒|"
    r"搭售|代销|存款|车贷|消费贷|贷款催收|个人信息"
)

# 处罚内容特征（用于识别真正的处罚决定，区分文号列）
_PENALTY_RE = re.compile(r"罚款|警告|禁止|没收|责令|取消|取消任职|终身")


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
                print(
                    f"  ! 请求失败({type(exc).__name__})，{wait}s 后重试"
                    f" {attempt + 1}/{retries}: {url}"
                )
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---------- 国家金融监督管理总局：行政处罚信息公开表 ----------

def fetch_nfra(max_docs: int) -> list[dict]:
    rows = _get(NFRA_LIST).json()["data"]["rows"]
    cases: list[dict] = []
    for doc in rows[:max_docs]:
        doc_id = doc["docId"]
        detail = _get(NFRA_DETAIL.format(doc_id=doc_id)).json()["data"]
        soup = BeautifulSoup(detail.get("docClob") or "", "lxml")
        table = soup.find("table")
        if table is None:
            print(f"  ! nfra doc {doc_id} 无表格，跳过")
            continue
        trs = table.find_all("tr")
        # 表头列序不固定，按表头名定位关键列
        header = [_clean(td.get_text()) for td in trs[0].find_all(["td", "th"])]
        try:
            i_name = header.index("当事人名称")
            i_fact = next(i for i, h in enumerate(header) if "违法违规" in h)
            i_penalty = next(
                i
                for i, h in enumerate(header)
                if ("处罚内容" in h or "行政处罚" in h) and "文号" not in h
            )
            i_org = next(i for i, h in enumerate(header) if "机关" in h)
        except (ValueError, StopIteration):
            print(f"  ! nfra doc {doc_id} 表头不识别: {header}，跳过")
            continue
        publish = (doc.get("publishDate") or "")[:10]
        for tr in trs[1:]:
            cells = [_clean(td.get_text()) for td in tr.find_all("td")]
            if len(cells) <= max(i_name, i_fact, i_penalty, i_org):
                continue
            org_name, violation = cells[i_org], cells[i_fact]
            if not cells[i_name] or not violation:
                continue
            # 个别表的"处罚内容"列只放文号：不含处罚关键词时扫同其他列兜底
            result = cells[i_penalty]
            if result and not _PENALTY_RE.search(result):
                for cell in cells:
                    if cell and cell not in (cells[i_name], violation) and _PENALTY_RE.search(cell):
                        result = cell
                        break
            cases.append(
                {
                    "case_name": f"{org_name}对{cells[i_name]}行政处罚案",
                    "penalty_org": org_name,
                    "penalty_date": publish or None,
                    "penalty_result": result[:500] or None,
                    "violation_summary": violation[:2000],
                    "source_url": NFRA_PAGE.format(doc_id=doc_id),
                    "source": "nfra",
                }
            )
        print(f"  + nfra doc {doc_id}: 累计 {len(cases)} 条")
    return cases


# ---------- 中国证监会：行政处罚决定书 ----------

def fetch_csrc(max_items: int) -> list[dict]:
    resp = _get(CSRC_HOME)
    resp.encoding = resp.charset_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        if not CSRC_URL_RE.match(a["href"]) or "行政处罚决定书" not in (a.get_text() or ""):
            continue
        if a["href"] in [h for _, h in links]:
            continue
        # 挂件条目带 MM-DD 日期（年份由决定书文号确定）
        parent = a.find_parent(["li", "div"])
        widget_date = ""
        if parent:
            m = re.search(r"(?:^|\s)(\d{2}-\d{2})(?:\s|$)", _clean(parent.get_text()))
            widget_date = m.group(1) if m else ""
        links.append((a["href"], widget_date))
    print(f"  首页挂件发现 {len(links)} 篇决定书，抓取前 {min(max_items, len(links))} 篇")

    cases: list[dict] = []
    for href, widget_date in links[:max_items]:
        url = "https://www.csrc.gov.cn" + href
        try:
            page = _get(url)
        except httpx.HTTPError as exc:
            print(f"  ! 抓取失败 {url}: {exc}")
            continue
        page.encoding = page.charset_encoding or "utf-8"
        node = BeautifulSoup(page.text, "lxml").select_one(".content")
        if node is None or len(node.get_text()) < 200:
            continue
        text = _clean(node.get_text())

        m_doc_no = re.search(r"〔(20\d{2})〕(\d+)号", text)
        doc_no = m_doc_no.group(0) if m_doc_no else None
        year = m_doc_no.group(1) if m_doc_no else None

        m_party = re.search(r"当事人[:：](.{2,60}?)[,，。]", text)
        party = m_party.group(1) if m_party else "相关当事人"
        party = re.sub(r"[（(]以下简称.*?[)）]", "", party).strip()

        # 违法事实段：优先取"存在以下违法事实:"之后
        m_facts = re.search(r"以下违法事实[:：]?(.{50,800}?)(?:上述违法事实|证据证明)", text)
        if not m_facts:
            m_facts = re.search(r"经查明[,，]?(.{50,800}?)(?:上述违法事实|证据证明)", text)
        facts = m_facts.group(1) if m_facts else text[200:700]

        m_decision = re.search(
            r"我会决定[:：](.{10,300}?)(?:。?\s*(?:上述当事人|当事人如果|$))", text
        )
        decision = None
        if m_decision:
            decision = m_decision.group(1).rstrip("。，") + "。"
        else:
            m_fine = re.search(r"([^。]*罚款[^。]{0,120}。)", text)
            decision = m_fine.group(1) if m_fine else None

        penalty_date = None
        if year and widget_date:
            penalty_date = f"{year}-{widget_date}"

        cases.append(
            {
                "case_name": f"中国证监会对{party}行政处罚案（{doc_no}）"
                if doc_no
                else f"中国证监会对{party}行政处罚案",
                "penalty_org": "中国证券监督管理委员会",
                "penalty_date": penalty_date,
                "penalty_result": decision,
                "violation_summary": facts[:2000],
                "source_url": url,
                "source": "csrc",
            }
        )
        print(f"  + csrc {doc_no}: {party}（{penalty_date or '日期缺失'}）")
    return cases


# ---------- 后处理 ----------

def _prioritize_and_cap(cases: list[dict], cap: int) -> list[dict]:
    relevant = [c for c in cases if _RELEVANT_RE.search(c["violation_summary"] or "")]
    others = [c for c in cases if c not in relevant]
    kept = relevant + others
    return kept[:cap]


def _match_regulations(cases: list[dict]) -> None:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import Regulation

        db = SessionLocal()
        names = [r.regulation_name for r in db.query(Regulation.regulation_name).all()]
        db.close()
    except Exception:
        print("  ! 法规库不可用，related_regulations 留空")
        return
    # 罚单正文多引用简称（《保险法》），库内为全名——别名映射补齐
    aliases: list[tuple[str, str]] = [
        (r"保险法", "中华人民共和国保险法（2015年修正）"),
        (r"证券投资基金法|基金法", "中华人民共和国证券投资基金法（2015年修正）"),
        (r"广告法", "中华人民共和国广告法（2021年修正）"),
        (r"消费者权益保护", "中华人民共和国消费者权益保护法（2013年修正）"),
        (r"金融消费者", "金融消费者权益保护实施办法"),
        (r"反洗钱", "中华人民共和国反洗钱法"),
        (r"个人信息", "中华人民共和国个人信息保护法"),
        (r"适当性", "证券期货投资者适当性管理办法"),
        (r"健康保险", "健康保险管理办法"),
        (r"保险销售", "保险销售行为管理办法"),
    ]
    name_set = set(names)
    matched = 0
    for case in cases:
        text = f"{case['violation_summary']} {case['penalty_result'] or ''}"
        hits = {n for n in names if n and n in text}
        for pattern, full_name in aliases:
            if re.search(pattern, text) and full_name in name_set:
                hits.add(full_name)
        if hits:
            case["related_regulations"] = sorted(hits)
            matched += 1
    print(f"  法规关联命中 {matched}/{len(cases)} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取真实监管处罚案例")
    parser.add_argument("--out", default="scripts/init_data/penalty_cases.json")
    parser.add_argument("--nfra-docs", type=int, default=6, help="NFRA 信息公开表文档数")
    parser.add_argument("--csrc", type=int, default=6, help="证监会决定书条数")
    parser.add_argument("--max", type=int, default=32, help="输出案例总数上限")
    args = parser.parse_args()

    print("== 抓取 国家金融监督管理总局 行政处罚信息公开表 ==")
    cases = fetch_nfra(args.nfra_docs)
    print("== 抓取 中国证监会 行政处罚决定书 ==")
    cases += fetch_csrc(args.csrc)

    # 按 case_name 去重（保留处罚结果信息更全的一条）后按相关性优先截断
    dedup: dict[str, dict] = {}
    for c in cases:
        old = dedup.get(c["case_name"])
        if old is None or len(str(c.get("penalty_result") or "")) > len(
            str(old.get("penalty_result") or "")
        ):
            dedup[c["case_name"]] = c
    cases = _prioritize_and_cap(list(dedup.values()), args.max)

    _match_regulations(cases)

    out = Path(args.out)
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成: {len(cases)} 条真实处罚案例 → {out}")
    by_source = {}
    for c in cases:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    print("来源分布:", by_source)


if __name__ == "__main__":
    main()
