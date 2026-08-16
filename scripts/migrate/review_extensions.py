"""幂等迁移：现存运行库增加批次/对比列与 review_batches 表。

注意：MySQL 8.0 不支持 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
（该语法为 MariaDB 专有，MySQL 8.0 直接语法报错），故改为先查询
information_schema 再补列/补索引，保证在 MySQL 8.0 上重复执行安全。

用法:
    python scripts/migrate/review_extensions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal

# (列名, 列定义)：缺哪列补哪列，已存在则跳过
_NEW_COLUMNS = (
    ("batch_id", "BIGINT UNSIGNED DEFAULT NULL"),
    ("base_document_name", "VARCHAR(255) DEFAULT NULL"),
    ("base_document_path", "VARCHAR(512) DEFAULT NULL"),
    ("diff_changes", "JSON DEFAULT NULL"),
)


def _existing_columns(db) -> set[str]:
    rows = db.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'review_tasks'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def _existing_indexes(db) -> set[str]:
    rows = db.execute(
        text(
            "SELECT INDEX_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'review_tasks'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def migrate() -> None:
    db = SessionLocal()
    try:
        cols = _existing_columns(db)
        for name, ddl in _NEW_COLUMNS:
            if name not in cols:
                db.execute(text(f"ALTER TABLE review_tasks ADD COLUMN {name} {ddl}"))
        idxs = _existing_indexes(db)
        if "idx_batch_id" not in idxs:
            db.execute(text("ALTER TABLE review_tasks ADD INDEX idx_batch_id (batch_id)"))
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS review_batches ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,"
            "batch_name VARCHAR(255) NOT NULL,"
            "status VARCHAR(16) NOT NULL DEFAULT 'running',"
            "total_count INT NOT NULL DEFAULT 0,"
            "completed_count INT NOT NULL DEFAULT 0,"
            "failed_count INT NOT NULL DEFAULT 0,"
            "created_by BIGINT UNSIGNED DEFAULT NULL,"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "completed_at DATETIME DEFAULT NULL,"
            "KEY idx_created_by (created_by)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        ))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
    print("review_extensions migration done")
