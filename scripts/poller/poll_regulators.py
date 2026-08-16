"""监管动态抓取入口：轮询监管机构发布源，发现新法规进待确认列表。

用法:
    python scripts/poller/poll_regulators.py            # 真实抓取入库 + LLM 打标
    python scripts/poller/poll_regulators.py --dry-run  # 只打印统计，不落库不调 LLM
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.infrastructure.database.mysql import SessionLocal
from src.services.regulation_monitor import fetch_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="监管动态抓取")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不落库不调 LLM")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = fetch_sources(db, dry_run=args.dry_run)
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
