"""Alembic 迁移环境。

设计要点：
- **连接串唯一来源**：src.utils.config.settings.mysql_url（.env 驱动），
  与 API/脚本运行时同源；不在 alembic.ini 重复维护，避免两处漂移。
- **元数据全量注册**：导入 src.models 包（17 个 ORM 模型），target_metadata
  才能覆盖全部业务表，autogenerate 的对比才是正确的。
- **checkpoint 表排除**：langgraph_checkpoints / langgraph_writes 由
  langgraph_saver.py 的幂等 DDL 兜底维护（结构随 langgraph-checkpoint 协议走），
  不参与 autogenerate 漂移检测——否则每次生成迁移都会提议 drop 它们。
  其新库建表快照在 0001 baseline 迁移中（手写 op.execute）。
- **-x dbname 覆盖**：校验脚本（scripts/maintenance/schema_drift_check.py）
  用它把迁移链指向临时库。
"""

import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from alembic import context
from sqlalchemy import create_engine, pool

# 兜底保证项目根可导入（alembic.ini 已设 prepend_sys_path，此处防手工调用场景）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.models  # noqa: E402,F401  导入即注册全部 ORM 模型到 Base.metadata
from src.infrastructure.database.mysql import Base  # noqa: E402
from src.utils.config import settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# langgraph checkpoint 两表：由 langgraph_saver.py 兜底维护，迁移链不检测、不删除
_EXCLUDED_TABLES = {"langgraph_checkpoints", "langgraph_writes"}


def include_object(object_, name, type_, reflected, compare_to):  # noqa: A002
    """autogenerate 过滤：checkpoint 表不参与（见模块 docstring）。"""
    if type_ == "table" and name in _EXCLUDED_TABLES:
        return False
    return True


def _target_url() -> str:
    """目标库连接串；支持 -x dbname=xxx 覆盖库名（漂移校验脚本用临时库）。"""
    url = settings.mysql_url
    dbname = context.get_x_argument(as_dictionary=True).get("dbname")
    if not dbname:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def run_migrations_offline() -> None:
    """离线模式（--sql）：只输出 SQL 不执行。"""
    context.configure(
        url=_target_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直连数据库执行。"""
    connectable = create_engine(_target_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 列类型变更纳入检测（如 VARCHAR 长度调整）
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
