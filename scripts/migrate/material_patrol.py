"""幂等迁移：台账发布渠道与巡检字段（R3 发布后监控）。

product_materials 补 5 列（publish_url/channel/content_fingerprint/
patrol_status/patrol_checked_at）。与既有迁移同一约定：先查
information_schema 再补列，重复执行安全。

用法:
    python scripts/migrate/material_patrol.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal

_NEW_COLUMNS = (
    (
        "product_materials",
        (
            ("publish_url", "VARCHAR(512) DEFAULT NULL COMMENT '已发布渠道直链（官网等授权渠道）'"),
            ("channel", "VARCHAR(32) DEFAULT NULL COMMENT '发布渠道 web/wechat/douyin'"),
            ("content_fingerprint", "TEXT DEFAULT NULL COMMENT '批准版规范化文本（巡检相似度基线）'"),
            ("patrol_status", "VARCHAR(16) DEFAULT NULL COMMENT 'ok/drift/changed/gone/error'"),
            ("patrol_checked_at", "DATETIME DEFAULT NULL COMMENT '最近巡检时间'"),
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
    )
    return {r[0] for r in rows}


def main() -> None:
    db = SessionLocal()
    try:
        for table, columns in _NEW_COLUMNS:
            existing = _existing_columns(db, table)
            if not existing:
                print(f"[skip] 表 {table} 不存在（先跑 init 建表）")
                continue
            for name, ddl in columns:
                if name in existing:
                    print(f"[skip] {table}.{name} 已存在")
                    continue
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                print(f"[ok] {table} 补列 {name}")
        db.commit()
        print("迁移完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
