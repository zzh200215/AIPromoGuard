"""外键迁移幂等循环校验（PR-7 验收①，可接 CI）。

在**临时库**上全程验证（不碰开发/演示库）：
  1. `alembic upgrade head` → 断言 21 条外键 + 11 个新索引齐全
  2. `alembic downgrade -1` → 断言外键与新增索引全部消失（对称可逆）
  3. `alembic upgrade head` → 再次断言齐全（幂等：可重复 upgrade/downgrade）
  4. 约束生效性抽查（真插入违规数据）：
     - 子行引用不存在的父行 → 应被拒（errno 1452）
     - 删除父行 → 子行应级联删除（CASCADE 真的在生效）
  5. finally 删除临时库

用法：
    python scripts/maintenance/fk_loop_check.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymysql
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.config import settings  # noqa: E402

EXPECT_FK = 21
EXPECT_NEW_INDEXES = 11
NEW_INDEXES = (
    "idx_results_rule_id",
    "idx_results_regulation_id",
    "idx_results_article_id",
    "idx_results_confirmed_by",
    "idx_link_article",
    "idx_link_created_by",
    "idx_sign_offs_user",
    "idx_assessment_penalty",
    "idx_assessment_created_by",
    "idx_assessment_confirmed_by",
    "idx_audit_user",
)


def _server_conn():
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
    )


def _tmp_db_url(dbname: str) -> str:
    parts = urlsplit(settings.mysql_url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _alembic(dbname: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"dbname={dbname}", *args],
        cwd=ROOT,
        check=True,
    )


def _fk_count(engine) -> int:
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
            )
        ).scalar()


def _index_present(engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
        ).fetchall()
    return {r[0] for r in rows}


_CHILD_COLS = (
    "(task_id, violation_type, risk_level, original_text, confidence_score, status)"
)


def _constraint_smoke(engine) -> None:
    """真插数据验证约束生效：孤儿被拒 + 父删级联。"""
    with engine.begin() as c:
        try:
            c.execute(
                text(
                    f"INSERT INTO review_results {_CHILD_COLS} "
                    "VALUES (999999999, 'rule', 'low', 'probe', 0, 'pending_confirm')"
                )
            )
            raise AssertionError("孤儿子行未被拒绝——外键未生效")
        except Exception as exc:  # noqa: BLE001
            assert "1452" in str(exc) or "foreign key" in str(exc).lower(), exc

        c.execute(
            text("INSERT INTO review_tasks (task_name, document_name) VALUES ('fk_probe', 'x.txt')")
        )
        task_id = c.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        c.execute(
            text(
                f"INSERT INTO review_results {_CHILD_COLS} "
                "VALUES (:tid, 'rule', 'low', 'probe', 0, 'pending_confirm')"
            ),
            {"tid": task_id},
        )
        c.execute(text("DELETE FROM review_tasks WHERE id = :tid"), {"tid": task_id})
        left = c.execute(
            text("SELECT COUNT(*) FROM review_results WHERE task_id = :tid"), {"tid": task_id}
        ).scalar()
        assert left == 0, f"父行删除后子行未级联（剩 {left} 行）"


def main() -> int:
    tmp_db = f"compliance_fk_loop_{int(time.time())}_{os.getpid()}"
    conn = _server_conn()
    try:
        print(f"[0/5] 建临时库 {tmp_db}")
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{tmp_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()

        print("[1/5] upgrade head → 断言外键/索引齐全")
        _alembic(tmp_db, "upgrade", "head")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            n = _fk_count(engine)
            idx = _index_present(engine)
        finally:
            engine.dispose()
        assert n == EXPECT_FK, f"外键数 {n} != {EXPECT_FK}"
        missing = [i for i in NEW_INDEXES if i not in idx]
        assert not missing, f"新增索引缺失：{missing}"
        print(f"  ✓ 外键 {n} 条；新增索引 {len(NEW_INDEXES)} 个齐全")

        print("[2/5] downgrade -1 → 断言对称可逆")
        _alembic(tmp_db, "downgrade", "-1")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            n0 = _fk_count(engine)
            idx = _index_present(engine)
        finally:
            engine.dispose()
        assert n0 == 0, f"downgrade 后仍剩 {n0} 条外键"
        leftover = [i for i in NEW_INDEXES if i in idx]
        assert not leftover, f"downgrade 后索引未清理：{leftover}"
        print("  ✓ 外键 0 条、新增索引全部移除")

        print("[3/5] upgrade head（第二轮）→ 幂等")
        _alembic(tmp_db, "upgrade", "head")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            n2 = _fk_count(engine)
        finally:
            engine.dispose()
        assert n2 == EXPECT_FK, f"二次 upgrade 后外键数 {n2} != {EXPECT_FK}"
        print(f"  ✓ 外键 {n2} 条（与首轮一致）")

        print("[4/5] 约束生效性抽查（真插数据）")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            _constraint_smoke(engine)
        finally:
            engine.dispose()
        print("  ✓ 孤儿子行被拒（errno 1452）；父行删除子行级联删除")

        print("PASS：upgrade→downgrade→upgrade 幂等循环通过，约束真实生效")
        return 0
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{tmp_db}`")
        conn.commit()
        conn.close()
        print(f"[5/5 cleanup] 临时库 {tmp_db} 已删除")


if __name__ == "__main__":
    sys.exit(main())
