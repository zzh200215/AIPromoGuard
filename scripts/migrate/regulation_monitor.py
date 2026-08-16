"""幂等迁移：现存运行库新建 regulation_updates 表（监管动态追踪）。

用法:
    python scripts/migrate/regulation_monitor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal


def migrate() -> None:
    db = SessionLocal()
    try:
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS regulation_updates ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,"
            "source VARCHAR(16) NOT NULL COMMENT '来源 nfra/csrc/pbc',"
            "title VARCHAR(255) NOT NULL COMMENT '法规名称',"
            "doc_no VARCHAR(64) DEFAULT NULL COMMENT '文号',"
            "publish_date DATE DEFAULT NULL,"
            "url VARCHAR(512) DEFAULT NULL COMMENT '原文链接',"
            "domain VARCHAR(32) DEFAULT NULL COMMENT 'LLM判定领域',"
            "doc_type VARCHAR(32) DEFAULT NULL COMMENT '规章/规范性文件/办法/公告',"
            "llm_summary VARCHAR(512) DEFAULT NULL COMMENT 'LLM摘要',"
            "matched_regulations JSON DEFAULT NULL COMMENT '匹配的库内法规',"
            "status VARCHAR(16) NOT NULL DEFAULT 'pending' "
            "COMMENT 'pending/imported/ignored/in_db',"
            "match_type VARCHAR(16) DEFAULT NULL COMMENT 'fetch/confirm/manual/in_db',"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "UNIQUE KEY uk_source_title (source, title)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        ))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
    print("regulation_monitor migration done")
