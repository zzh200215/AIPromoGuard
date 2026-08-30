"""review_tasks 增加成本归因字段（llm_usage JSON，幂等）。

已有库升级用：python scripts/migrate/task_llm_usage.py
CI/新库不需要——create_all 按模型建表即含该列。
"""

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal


def migrate() -> None:
    db = SessionLocal()
    try:
        existing = {
            row[0] for row in db.execute(text("SHOW COLUMNS FROM review_tasks")).fetchall()
        }
        if "llm_usage" in existing:
            print("review_tasks.llm_usage already exists")
            return
        db.execute(
            text(
                "ALTER TABLE review_tasks ADD COLUMN llm_usage JSON NULL "
                "COMMENT 'LLM token 用量/预估成本（成本归因）' AFTER stages"
            )
        )
        db.commit()
        print("added review_tasks.llm_usage")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
