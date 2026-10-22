"""按情报里已存的详情页 URL 直取法规全文（"人工补录"通道）。

适用场景：`fetch_regulations.py` 靠标题在三大源索引里模糊匹配，索引没收录的文件
（例如金监总局的"通知/批复"类、证监会指定页）永远匹配不上。但 `regulation_updates`
每条情报都存着原始详情页 URL——直接按 URL 取正文即可，绕开索引匹配。

分派规则：
- nfra：URL 里的 docId → 走 `nfra_fetch`（docClob 段落提取 + 附件兜底）
- csrc：直接 `csrc_fetch`（文字版 docx 优先）
- pbc ：详情页 `div#zoom` / `td.content`

用法（仓库根目录）：
    python scripts/crawl/backfill_from_url.py --ids 90,94,2705 --dry-run
    python scripts/crawl/backfill_from_url.py --ids 90,94 --json out.json --import
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import fetch_regulations as fr  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402
from src.infrastructure.database.mysql import engine  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

OUT_DIR = Path("data/tmp/backfill")


def _rows(ids: list[int] | None, limit: int) -> list[tuple]:
    where = "status='pending'"
    params: dict = {}
    if ids:
        placeholders = ",".join(f":i{n}" for n in range(len(ids)))
        where += f" AND id IN ({placeholders})"
        params = {f"i{n}": v for n, v in enumerate(ids)}
    sql = f"SELECT id, source, title, domain, url FROM regulation_updates WHERE {where} ORDER BY id"
    if limit:
        sql += f" LIMIT {limit}"
    with engine.connect() as conn:
        return conn.execute(sql_text(sql), params).fetchall()


def _fetch_by_url(source: str, url: str) -> tuple[str, str | None]:
    if source == "nfra":
        m = re.search(r"docId=(\d+)", url or "")
        if not m:
            raise ValueError("NFRA URL 里没有 docId")
        return fr.nfra_fetch(int(m.group(1)))
    if source == "csrc":
        return fr.csrc_fetch(url)
    if source == "pbc":
        from bs4 import BeautifulSoup

        resp = fr._get(url)
        resp.encoding = resp.charset_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        node = soup.select_one("div#zoom") or soup.select_one("td.content")
        return (node.get_text("\n", strip=True) if node else ""), None
    raise ValueError(f"未知来源 {source}")


def main() -> None:
    ap = argparse.ArgumentParser(description="按 URL 直取法规全文并回填")
    ap.add_argument("--ids", default="", help="指定 update id（逗号分隔），默认全部 pending")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--no-llm", action="store_true", default=True, help="默认不调 LLM（保留参数占位）"
    )
    ap.add_argument(
        "--min-articles",
        type=int,
        default=5,
        help="最少条款数（默认 5）。通知/意见类只有「一、二、三」章节，可调低到 3",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--import", dest="do_import", action="store_true", help="导入数据库并回写状态")
    args = ap.parse_args()

    ids = [int(x) for x in args.ids.split(",") if x.strip()] or None
    rows = _rows(ids, args.limit)
    print(f"== 待回填 {len(rows)} 条 ==")

    items, ok_ids, skipped = [], [], []
    for uid, source, title, domain, url in rows:
        if not url:
            skipped.append((uid, "无 URL"))
            continue
        try:
            text, doc_no = _fetch_by_url(source, url)
        except Exception as exc:  # noqa: BLE001
            skipped.append((uid, f"{type(exc).__name__}: {exc}"))
            continue
        if len(text or "") < 300:
            skipped.append((uid, f"正文过短({len(text or '')}字)"))
            continue
        entry = {"regulation_name": title, "domain": domain or "other"}
        meta = {
            "source": source,
            "source_id": url[-40:],
            "source_url": url,
            "issuer": "",
            "source_title": title,
            "date": None,
            "fetched_at": date.today().isoformat(),
        }
        reg = fr._finish(entry, text, doc_no, meta, None, min_articles=args.min_articles)
        if not reg:
            skipped.append((uid, "条款切分不足"))
            continue
        items.append(reg)
        ok_ids.append(uid)
        print(f"  + #{uid} {len(reg['articles'])} 条 / {reg['regulation_name'][:32]}")
        time.sleep(0.6)

    print(f"== 成功 {len(items)} / {len(rows)} ==")
    for uid, reason in skipped:
        print(f"  - #{uid} {reason}")
    if args.dry_run or not items:
        return

    out = Path(args.out) if args.out else OUT_DIR / f"backfill_{date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = [{k: v for k, v in d.items() if not k.startswith("_")} for d in items]
    # 导入器不接受空串日期（MySQL 严格模式报 1292），统一置 None
    for d in clean:
        for k in ("publish_date", "effective_date"):
            v = d.get(k)
            if isinstance(v, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.strip()):
                d[k] = None
    out.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"草稿已写入: {out}")

    if args.do_import:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "init_data"))
        from importlib import import_module

        sys.argv = ["import_regulations", "--json", str(out)]
        import_module("import_regulations").main()
        with engine.begin() as conn:
            for uid in ok_ids:
                conn.execute(
                    sql_text(
                        "UPDATE regulation_updates SET status='imported', match_type='url' "
                        "WHERE id=:i"
                    ),
                    {"i": uid},
                )
        print(f"已回写 {len(ok_ids)} 条状态为 imported")


if __name__ == "__main__":
    main()
