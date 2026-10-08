"""schema 漂移校验：迁移链产物 vs ORM 模型元数据（PR-0a 验收工具，可接 CI）。

做的事（全程只碰临时库，不影响开发/演示库）：
1. 建临时库（compliance_drift_check_<时间戳>_<pid>）
2. 对临时库跑完整迁移链（子进程 `alembic -x dbname=... upgrade head`）
3. 用 alembic compare_metadata 对比迁移产物与 src.models 的 ORM 元数据——应零差异
4. 断言表清单齐全（17 张 ORM 表 + 2 张 langgraph checkpoint 表）
5. 无论成败，finally 删除临时库

用途：
- 验收 0001 baseline 迁移与 ORM 模型完全一致（"upgrade 库 vs create_all 库 diff 为空"的强口径：
  compare_metadata 就是 autogenerate 的判断器，空 diff = 元数据语义级一致）
- 长期护栏：模型改了但忘写迁移 → 退出码 1（可接 CI 在 Init schema 后追加一步）

用法：
    python scripts/maintenance/schema_drift_check.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymysql
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.models  # noqa: E402,F401  导入即注册全部 ORM 模型
from src.infrastructure.database.mysql import Base  # noqa: E402
from src.utils.config import settings  # noqa: E402

# langgraph checkpoint 两表：由 langgraph_saver.py 兜底维护，不参与 autogenerate
# 检测（与 migrations/env.py 的 include_object 保持同步）
_EXCLUDED_TABLES = {"langgraph_checkpoints", "langgraph_writes"}


def _server_conn():
    """到 MySQL server 的连接（不指定库），用于建/删临时库。"""
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


def _include_object(object_, name, type_, reflected, compare_to):  # noqa: A002
    if type_ == "table" and name in _EXCLUDED_TABLES:
        return False
    return True


def main() -> int:
    tmp_db = f"compliance_drift_check_{int(time.time())}_{os.getpid()}"
    conn = _server_conn()
    try:
        print(f"[1/4] 建临时库 {tmp_db}")
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{tmp_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()

        print("[2/4] 对临时库跑完整迁移链（alembic upgrade head）")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-x", f"dbname={tmp_db}", "upgrade", "head"],
            cwd=ROOT,
            check=True,
        )

        print("[3/4] compare_metadata：迁移产物 vs ORM 元数据")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            with engine.connect() as c:
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext

                mc = MigrationContext.configure(c, opts={"include_object": _include_object})
                diffs = compare_metadata(mc, Base.metadata)
        finally:
            engine.dispose()

        if diffs:
            print(f"✗ 发现 {len(diffs)} 处漂移（迁移链与 ORM 模型不一致）：")
            for d in diffs:
                print(f"  - {d}")
            return 1
        print("  ✓ 零差异")

        print("[4/4] 表清单断言")
        engine = create_engine(_tmp_db_url(tmp_db))
        try:
            actual = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        actual.discard("alembic_version")  # alembic 自管表不计
        expected = set(Base.metadata.tables) | _EXCLUDED_TABLES
        missing, extra = expected - actual, actual - expected
        if missing or extra:
            print(f"✗ 表清单不符：缺 {sorted(missing)}；多 {sorted(extra)}")
            return 1
        print(f"  ✓ {len(expected)} 张表齐全（{len(Base.metadata.tables)} ORM + "
              f"{len(_EXCLUDED_TABLES)} checkpoint）")

        print("PASS：迁移链与 ORM 模型一致，无漂移")
        return 0
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{tmp_db}`")
        conn.commit()
        conn.close()
        print(f"[cleanup] 临时库 {tmp_db} 已删除")


if __name__ == "__main__":
    sys.exit(main())
