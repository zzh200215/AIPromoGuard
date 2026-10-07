"""notifications 表迁移（幂等）。已有库升级用：

PYTHONPATH=. python scripts/migrate/notifications.py
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
                CREATE TABLE IF NOT EXISTS notifications (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    user_id BIGINT NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    body VARCHAR(512) NULL,
                    link VARCHAR(255) NULL,
                    is_read TINYINT NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_notifications_user (user_id, is_read)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
        db.commit()
        print("notifications table ready")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
