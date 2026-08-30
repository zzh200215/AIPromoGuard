"""review_tasks 增加审查策略字段（profile VARCHAR(16)，幂等）。

已有库升级用：PYTHONPATH=. python scripts/migrate/task_profile.py
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
        if "profile" in existing:
            print("review_tasks.profile already exists")
            return
        db.execute(
            text(
                "ALTER TABLE review_tasks ADD COLUMN profile VARCHAR(16) NULL "
                "COMMENT '审查策略 strict/standard/loose（NULL=standard）' AFTER domain"
            )
        )
        db.commit()
        print("added review_tasks.profile")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
