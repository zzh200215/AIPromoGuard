"""外键图三方一致性锁（PR-7）。

同一张外键图出现在三个地方，任何一处漂移都会造成"迁移建了但模型不知道"
（drift check 报错）或"清洗脚本漏了一列"（迁移建 FK 时 errno 1452）：

1. `migrations/versions/*_add_foreign_keys.py::FKS` —— 迁移冻结副本（DDL 权威）
2. `scripts/maintenance/orphan_cleanup.py::FK_SPECS` —— 运维清洗清单
3. `src/models/*.py` 的 ForeignKey 声明 —— ORM 元数据（drift check 的对比基准）

本测试机械校验三者一致，替代"靠人记住同步"。
"""

import importlib.util
import sys
from pathlib import Path

import src.models  # noqa: F401  导入即注册全部 ORM 模型
from src.infrastructure.database.mysql import Base

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # 必须先注册进 sys.modules：清洗脚本用了 @dataclass，dataclasses 解析注解时
    # 会回查 sys.modules[cls.__module__]，未注册则 AttributeError
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _migration_module():
    files = sorted((ROOT / "migrations" / "versions").glob("*_add_foreign_keys.py"))
    assert files, "未找到 add_foreign_keys 迁移"
    return _load_module("pr7_migration", files[-1])


def _cleanup_script():
    return _load_module(
        "pr7_cleanup", ROOT / "scripts" / "maintenance" / "orphan_cleanup.py"
    )


def _migration_specs() -> set[tuple[str, str, str, str, str]]:
    mod = _migration_module()
    return {(f[0], f[1], f[2], f[3], f[4]) for f in mod.FKS}


def _cleanup_specs() -> set[tuple[str, str, str, str, str]]:
    mod = _cleanup_script()
    return {
        (s.child, s.child_col, s.parent, s.parent_col, s.ondelete) for s in mod.FK_SPECS
    }


def _orm_specs() -> dict[str, tuple[str, str, str, str, str]]:
    out = {}
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            element = list(fk.elements)[0]
            out[fk.name] = (
                table.name,
                element.parent.name,
                element.column.table.name,
                element.column.name,
                fk.ondelete or "",
            )
    return out


def test_migration_matches_cleanup_script():
    """迁移冻结副本与运维清洗清单必须逐字段一致（含 ondelete 策略）。"""
    mig, cleanup = _migration_specs(), _cleanup_specs()
    assert mig == cleanup, f"迁移与清洗脚本漂移：迁移独有 {mig - cleanup}；脚本独有 {cleanup - mig}"


def test_orm_declares_every_fk():
    """ORM 必须声明全部外键（否则 schema_drift_check 会报"迁移建了模型没有"）。"""
    mig = _migration_specs()
    orm = _orm_specs()
    orm_tuples = set(orm.values())
    missing = mig - orm_tuples
    assert not missing, f"ORM 缺少外键声明：{sorted(missing)}"
    extra = orm_tuples - mig
    assert not extra, f"ORM 多出迁移未建的外键：{sorted(extra)}"


def test_fk_names_match_migration():
    """外键名必须与迁移一致（Alembic 按名对比约束，名字漂移=每次 drift 报 diff）。"""
    mod = _migration_module()
    mig = {f[5]: f for f in mod.FKS}
    orm = _orm_specs()
    assert set(mig) == set(orm), (
        f"外键名不一致：迁移独有 {sorted(set(mig) - set(orm))}；"
        f"ORM 独有 {sorted(set(orm) - set(mig))}"
    )


def test_polymorphic_columns_have_no_fk():
    """多态/文件引用列不得建外键（PR-7 方案明确排除，避免约束语义错误）。"""
    orm_cols = {(t, c) for t, c, *_ in _orm_specs().values()}
    for table, col in (
        ("review_batches", "source_id"),
        ("audit_logs", "resource_id"),
        ("product_materials", "document_id"),
    ):
        assert (table, col) not in orm_cols, f"{table}.{col} 是引用列，不应建外键"


def test_fk_count_and_rules():
    """数量与删除规则快照（21 条；CASCADE 强从属 / SET NULL 弱引用 / RESTRICT 审计）。"""
    mig = _migration_specs()
    assert len(mig) == 21
    rules = {}
    for _child, _col, _parent, _pcol, rule in mig:
        rules[rule] = rules.get(rule, 0) + 1
    assert rules == {"CASCADE": 6, "SET NULL": 14, "RESTRICT": 1}
