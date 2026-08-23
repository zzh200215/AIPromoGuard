"""幂等迁移：法规影响中心数据层。

新建 rule_regulation_links / product_materials / impact_assessments 三张表，
并为 rules 补 status（生效生命周期）、review_batches 补 source_type/source_id
（批次溯源到影响评估）两处列。

与 review_extensions.py 同一约定：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，
先查 information_schema 再补列，重复执行安全。

用法:
    python scripts/migrate/impact_center.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal

# (表名, [(列名, 列定义)])：缺哪列补哪列，已存在则跳过
_NEW_COLUMNS = (
    ("rules", (("status", "VARCHAR(16) NOT NULL DEFAULT 'active'"),)),
    (
        "review_batches",
        (
            ("source_type", "VARCHAR(32) DEFAULT NULL COMMENT 'manual/impact_assessment'"),
            ("source_id", "BIGINT UNSIGNED DEFAULT NULL COMMENT '来源记录 id'"),
        ),
    ),
)


def _existing_columns(db, table: str) -> set[str]:
    rows = db.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table},
    ).fetchall()
    return {row[0] for row in rows}


def _create_tables(db) -> None:
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rule_regulation_links ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,"
            "rule_id BIGINT UNSIGNED NOT NULL COMMENT '关联规则',"
            "regulation_id BIGINT UNSIGNED DEFAULT NULL COMMENT '库内法规',"
            "article_id BIGINT UNSIGNED DEFAULT NULL COMMENT '具体条款',"
            "citation VARCHAR(255) DEFAULT NULL COMMENT '引用文本',"
            "link_type VARCHAR(16) NOT NULL DEFAULT 'support' COMMENT 'support/derive',"
            "source VARCHAR(16) NOT NULL DEFAULT 'manual' COMMENT 'manual/impact_analysis',"
            "created_by BIGINT UNSIGNED DEFAULT NULL,"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "KEY idx_link_rule (rule_id),"
            "KEY idx_link_regulation (regulation_id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
            "COMMENT='规则与法规条款关联表'"
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS product_materials ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,"
            "name VARCHAR(255) NOT NULL COMMENT '材料名称',"
            "product_type VARCHAR(32) NOT NULL COMMENT 'fund/insurance/wealth',"
            "material_type VARCHAR(32) NOT NULL COMMENT '宣传单页/海报/推文/话术稿',"
            "version VARCHAR(32) NOT NULL DEFAULT 'v1',"
            "owner VARCHAR(64) DEFAULT NULL COMMENT '负责人',"
            "document_id VARCHAR(64) DEFAULT NULL COMMENT '关联待审文档 doc_xxxxxxxx',"
            "status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active/archived',"
            "last_review_status VARCHAR(16) DEFAULT NULL COMMENT 'clean/violation/failed',"
            "last_reviewed_at DATETIME DEFAULT NULL,"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "KEY idx_material_product (product_type, status)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
            "COMMENT='产品材料台账表'"
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS impact_assessments ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,"
            "regulation_update_id BIGINT UNSIGNED DEFAULT NULL COMMENT '触发源:监管动态',"
            "penalty_case_id BIGINT UNSIGNED DEFAULT NULL COMMENT '触发源:处罚案例',"
            "title VARCHAR(255) NOT NULL,"
            "summary VARCHAR(1024) DEFAULT NULL COMMENT '评估结论摘要',"
            "status VARCHAR(16) NOT NULL DEFAULT 'draft' "
            "COMMENT 'draft/pending_review/confirmed/dismissed',"
            "items JSON DEFAULT NULL COMMENT '影响明细:受影响规则与材料及风险等级',"
            "high_count INT NOT NULL DEFAULT 0,"
            "medium_count INT NOT NULL DEFAULT 0,"
            "low_count INT NOT NULL DEFAULT 0,"
            "created_by BIGINT UNSIGNED DEFAULT NULL,"
            "confirmed_by BIGINT UNSIGNED DEFAULT NULL,"
            "confirmed_at DATETIME DEFAULT NULL,"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "KEY idx_assessment_update (regulation_update_id),"
            "KEY idx_assessment_status (status)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
            "COMMENT='法规影响评估表'"
        )
    )


def _add_columns(db) -> None:
    for table, columns in _NEW_COLUMNS:
        existing = _existing_columns(db, table)
        for name, definition in columns:
            if name in existing:
                continue
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def migrate() -> None:
    db = SessionLocal()
    try:
        _create_tables(db)
        _add_columns(db)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
    print("impact_center migration done")
