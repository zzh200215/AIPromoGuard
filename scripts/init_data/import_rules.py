"""预置规则引擎启动集（20 条高频规则）。

数据来源: 公开渠道整理的金融产品违规高发模式（见同目录 rules.json）。
幂等: 按 (domain, rule_name) upsert；已存在且内容未变的跳过，更新时 version 自增。

用法:
    python scripts/init_data/import_rules.py [--json 文件路径]
默认读取 scripts/init_data/rules.json。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.models import Rule

DEFAULT_JSON = Path(__file__).resolve().parent / "rules.json"


def _upsert_rule(db, item: dict) -> tuple[bool, bool]:
    row = (
        db.query(Rule)
        .filter(Rule.domain == item["domain"], Rule.rule_name == item["rule_name"])
        .first()
    )
    fields = {**item, "is_active": 1 if item.get("is_active", True) else 0}
    if row is None:
        db.add(Rule(**fields))
        return True, False
    changed = any(getattr(row, k) != v for k, v in fields.items())
    if changed:
        for k, v in fields.items():
            setattr(row, k, v)
        row.version += 1
        return False, True
    return False, False


def main() -> None:
    json_path = (
        Path(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else DEFAULT_JSON
    )
    with json_path.open(encoding="utf-8") as f:
        items = json.load(f)

    db = SessionLocal()
    try:
        added = updated = 0
        for item in items:
            is_added, is_updated = _upsert_rule(db, item)
            added += is_added
            updated += is_updated
        db.commit()
        print(f"完成: 规则总数 {len(items)}, 新增 {added}, 更新 {updated}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
