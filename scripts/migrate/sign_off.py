"""task_sign_offs 表迁移（幂等）。已有库升级用：

PYTHONPATH=. python scripts/migrate/sign_off.py
CI/新库不需要——create_all 按模型建表即含该表。
"""

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal


def migrate() -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS task_sign_offs (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username VARCHAR(64) NOT NULL,
                    decision VARCHAR(16) NOT NULL,
                    note TEXT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_task_sign_offs_task (task_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
        db.commit()
        print("task_sign_offs table ready")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
