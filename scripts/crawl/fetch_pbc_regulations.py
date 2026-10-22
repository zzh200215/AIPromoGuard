"""抓取中国人民银行规章全文并入库（补上三源覆盖不到的 PBC 缺口）。

背景：fetch_regulations.py 覆盖 国务院 / 金监总局 / 证监会 三源，PBC 规章不在其中，
导致 regulation_updates 里大量 pbc 待确认条目永远「未命中，走人工兜底」。
实测（2026-10-19）：PBC 详情页静态可抓，正文在 div#zoom（td.content 兜底），
「第X条」锚点齐全——**确定性切分即可，不调用 LLM**。

流程：
  读取 regulation_updates(status=pending, source=pbc)
  → 逐条抓详情页 → 抽正文 → extract_articles 切条款 → numbering_quality 质检
  → 产出 JSON（import_regulations 可直接吃）
  → 可选 --import：导入法规+条款并回写 update.status='imported'

用法:
    python scripts/crawl/fetch_pbc_regulations.py --limit 3 --dry-run    # 试点
    python scripts/crawl/fetch_pbc_regulations.py                        # 全量抓取（只落 JSON）
    python scripts/crawl/fetch_pbc_regulations.py --import               # 抓取 + 入库 + 回写状态
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "crawl"))

import httpx  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from fetch_regulations import extract_articles, numbering_quality  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from src.utils.config import settings  # noqa: E402

OUT_DIR = ROOT / "scripts/init_data/pending/regulations"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_DOC_NO_RE = re.compile(r"〔\d{4}〕第\d+号")
_INNER_TITLE_RE = re.compile(r"[（(]([^（）()]{6,})[）)]")
_EFFECTIVE_RE = re.compile(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行")


def _clean_title(title: str) -> str:
    """『中国人民银行令〔2026〕第3号（中国人民银行行政复议办法）』→ 内层法规名。"""
    m = _INNER_TITLE_RE.search(title)
    if m and ("办法" in m.group(1) or "规定" in m.group(1) or "决定" in m.group(1)):
        return m.group(1).strip()
    return re.sub(r"^中国人民银行令", "", title).strip()


def _fetch(url: str) -> str:
    resp = httpx.get(url, headers=_UA, timeout=25, follow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.charset_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    node = soup.select_one("div#zoom") or soup.select_one("td.content")
    if node is None:
        return ""
    return node.get_text("\n", strip=True)


def _effective_date(body: str) -> str | None:
    m = _EFFECTIVE_RE.search(body)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def build_item(update_id: int, title: str, url: str, domain: str | None) -> dict | None:
    body = _fetch(url)
    if not body or len(body) < 300:
        print(f"  ! #{update_id} 正文过短（{len(body)} 字），跳过")
        return None
    articles = extract_articles(body)
    quality = numbering_quality(articles)
    if not articles:
        print(f"  ! #{update_id} 未切出条款，跳过")
        return None
    doc_no_match = _DOC_NO_RE.search(title)
    item = {
        "domain": domain if domain in ("banking", "fund", "insurance") else "banking",
        "regulation_name": _clean_title(title),
        "regulation_no": (
            f"中国人民银行令{doc_no_match.group(0)}" if doc_no_match else title
        ),
        "issuer": "中国人民银行",
        "publish_date": None,
        "effective_date": _effective_date(body),
        "status": "effective",
        "articles": articles,
    }
    print(
        f"  + #{update_id} {item['regulation_name'][:30]} | {len(articles)} 条 | "
        f"编号质量 {quality:.2f} | 正文 {len(body)} 字"
    )
    if quality < 0.8:
        print("    ! 条号连续性偏低，建议人工抽验")
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数（0=全部）")
    parser.add_argument("--ids", default="", help="指定 update id（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不落盘不导入")
    parser.add_argument("--import", dest="do_import", action="store_true", help="导入数据库")
    parser.add_argument("--out", default="", help="输出 JSON 路径")
    parser.add_argument("--reuse", default="", help="复用已抓取草稿（跳过抓取，直接导入）")
    args = parser.parse_args()

    engine = create_engine(settings.mysql_url)
    where, params = ["status='pending'", "source='pbc'"], {}
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        where.append(f"id IN ({','.join(str(i) for i in ids)})")
    sql = (
        f"SELECT id, title, url, domain FROM regulation_updates "
        f"WHERE {' AND '.join(where)} ORDER BY id"
    )
    if args.limit:
        sql += f" LIMIT {args.limit}"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    print(f"== 待抓取 PBC 条目 {len(rows)} 条 ==")
    items, ok_ids = [], []
    if args.reuse:
        # 复用既有草稿：按「清洗后标题」反查 update id，跳过抓取
        items = json.loads(Path(args.reuse).read_text(encoding="utf-8"))
        title_map = {_clean_title(t): i for i, t, _u, _d in rows}
        ok_ids = [
            title_map[it["regulation_name"]]
            for it in items
            if it["regulation_name"] in title_map
        ]
        print(f"== 复用草稿 {len(items)} 条（匹配到 update {len(ok_ids)} 条）==")
    else:
        for update_id, title, url, domain in rows:
            if not url:
                print(f"  ! #{update_id} 无详情页 URL，跳过")
                continue
            try:
                item = build_item(update_id, title, url, domain)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! #{update_id} 抓取失败: {exc}")
                item = None
            if item:
                items.append(item)
                ok_ids.append(update_id)
            time.sleep(0.8)  # 限速，别把政府站当压测目标

    print(f"== 成功 {len(items)} / {len(rows)} ==")
    if args.dry_run or not items:
        return

    out = (
        Path(args.reuse)
        if args.reuse
        else (Path(args.out) if args.out else OUT_DIR / f"pbc_{datetime.now():%Y%m%d_%H%M%S}.json")
    )
    if not args.reuse:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"草稿已写入: {out}")

    if args.do_import:
        sys.path.insert(0, str(ROOT / "scripts" / "init_data"))
        from importlib import import_module

        sys.argv = ["import_regulations", "--json", str(out)]
        import_module("import_regulations").main()
        with engine.begin() as conn:
            for update_id in ok_ids:
                conn.execute(
                    text(
                        "UPDATE regulation_updates SET status='imported', match_type='pbc' "
                        "WHERE id=:i"
                    ),
                    {"i": update_id},
                )
        print(f"已回写 {len(ok_ids)} 条 update 状态为 imported")


if __name__ == "__main__":
    main()
