"""初始化测试数据库 fcr_test：建库 + 建表 + 灌基础种子（幂等）。

用途：tests/conftest.py 把全部测试流量切到 fcr_test（根治 2026-10-13
"测试污染真库"问题）。首次跑测试前执行一次；之后测试的写删都落在
fcr_test 内，真库不再受影响。--reset 清库重灌（表结构与种子回到初始）。

用法:
    python scripts/dev/init_test_db.py [--reset]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["MYSQL_DATABASE"] = "fcr_test"  # 必须先于任何 src 导入

import src.models  # noqa: F401  导入模型包：把全部表注册进 Base.metadata（否则 create_all 建空库）
from sqlalchemy import create_engine, text
from src.infrastructure.database.mysql import Base, engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

TEST_DB = "fcr_test"
_SEEDERS = [
    "scripts/init_data/import_regulations.py",
    "scripts/init_data/import_rules.py",
    "scripts/init_data/import_penalty_cases.py",
    "scripts/init_data/init_admin.py",
]


def main() -> None:
    reset = "--reset" in sys.argv

    # 1) 建库（服务器级连接，不带库名；注意 str(engine.url) 会掩码密码，必须用 URL 对象）
    server = create_engine(engine.url.set(database=None))
    with server.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS {TEST_DB} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        conn.commit()
    server.dispose()

    # 2) --reset：清空全部表（关外键检查保顺序无关）
    if reset:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
            for t in tables:
                conn.execute(text(f"DROP TABLE `{t}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        logger.info("已清空 %s 的 %s 张表", TEST_DB, len(tables))

    # 3) 建表（按模型元数据建缺失表；已有表不动 → 幂等）
    Base.metadata.create_all(engine)

    # 4) 灌种子（子进程继承 MYSQL_DATABASE=fcr_test；导入脚本自身按业务键 upsert）
    root = Path(__file__).resolve().parents[2]
    for script in _SEEDERS:
        r = subprocess.run(
            [sys.executable, str(root / script)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            env={**os.environ},
        )
        if r.returncode == 0:
            print(f"  {Path(script).name}: ok")
        else:
            tail = (r.stdout or "")[-200:] + (r.stderr or "")[-200:]
            print(f"  {Path(script).name}: FAIL {tail}")

    with engine.connect() as conn:
        counts = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            for t in ("regulations", "rules", "penalty_cases", "users")
        }
    print(f"{TEST_DB} 就绪: {counts}")


if __name__ == "__main__":
    main()
