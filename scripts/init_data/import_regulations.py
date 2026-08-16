"""导入法规知识库（regulations + articles 表）。

数据来源: 公开渠道整理的核心金融法规（见同目录 regulations.json）。
幂等: 按文号(regulation_no) upsert 法规，按(regulation_id, article_no) upsert 条款；
      已存在且内容未变的跳过，不产生重复。

用法:
    python scripts/init_data/import_regulations.py [--json 文件路径]
默认读取 scripts/init_data/regulations.json。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.models import Article, Regulation

DEFAULT_JSON = Path(__file__).resolve().parent / "regulations.json"


def _upsert_regulation(db, item: dict) -> Regulation:
    reg = db.query(Regulation).filter(Regulation.regulation_no == item["regulation_no"]).first()
    fields = {k: v for k, v in item.items() if k != "articles"}
    if reg is None:
        reg = Regulation(**fields)
        db.add(reg)
        db.flush()
        print(f"  + 法规: {reg.regulation_name}")
    else:
        changed = any(getattr(reg, k) != v for k, v in fields.items())
        if changed:
            for k, v in fields.items():
                setattr(reg, k, v)
            print(f"  ~ 更新法规: {reg.regulation_name}")
    return reg


def _upsert_articles(db, reg: Regulation, articles: list[dict]) -> int:
    added = updated = 0
    for a in articles:
        row = (
            db.query(Article)
            .filter(Article.regulation_id == reg.id, Article.article_no == a["article_no"])
            .first()
        )
        if row is None:
            db.add(Article(regulation_id=reg.id, **a))
            added += 1
        elif row.content != a["content"]:
            for k, v in a.items():
                setattr(row, k, v)
            updated += 1
    return added, updated


def main() -> None:
    json_path = (
        Path(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else DEFAULT_JSON
    )
    with json_path.open(encoding="utf-8") as f:
        items = json.load(f)

    db = SessionLocal()
    try:
        total_a = total_u = 0
        for item in items:
            reg = _upsert_regulation(db, item)
            added, updated = _upsert_articles(db, reg, item.get("articles", []))
            total_a += added
            total_u += updated
        db.commit()
        print(f"完成: {len(items)} 部法规, 新增条款 {total_a}, 更新条款 {total_u}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
