"""add foreign keys (PR-7)

Revision ID: 1d7ed1680920
Revises: 2a3d1834110c
Create Date: 2026-10-09 19:40:00.000000

给 9 张子表补 21 条外键（PR-7 工程债：DB 约束是应用层一致性逻辑的保险丝）：

- **强从属 CASCADE**：articles→regulations、review_results→review_tasks、
  rule_regulation_links→rules/regulations、task_sign_offs→review_tasks、
  notifications→users（父行没了，子行本身失去意义）
- **弱引用 SET NULL**：rule_id / regulation_id / article_id / created_by /
  confirmed_by / batch_id / 影响中心触发源（历史结论与留痕必须保留，只断指针）
- **审计证据 RESTRICT**：task_sign_offs.user_id（签字人不可硬删，保住签发留痕）

不建外键的列（多态引用，见各模型注释）：review_batches.source_id、
audit_logs.resource_id、product_materials.document_id。

显式索引 11 个（外键列必需）——显式命名避免 MySQL 自动命名（fk_*）漂移，
与 ORM 的 Index 声明一一对应；notifications.user_id 复用既有复合索引
idx_notifications_user（user_id 为首列，满足 MySQL 外键索引要求）。

**既有库兼容**：dev 库部分表由已废弃的 init_mysql.sql 建（BIGINT UNSIGNED），
后加表由 ORM 建（BIGINT），并存导致 4 处子列与父列类型不一致——直接建 FK 会
报 errno 3780（类型不兼容）。`_align_column_types` 按**父列实际类型**对齐子列
（保留可空性）；全新库两侧同为 BIGINT，该步为 no-op。

**回滚**：downgrade 逐条 drop FK + 仅 drop 本迁移创建的索引（对称可逆）。
列类型对齐不回滚——它是"一次性的兼容修正"（回滚后再 upgrade 会再次对齐，
无净收益），且回退到 signed 没有任何业务意义。

前置：`python scripts/maintenance/orphan_cleanup.py --apply`（孤儿行会被
MySQL 拒绝，errno 1452）。审计落盘 data/audits/orphan_cleanup_<时间>.json。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1d7ed1680920"
down_revision: str | None = "2a3d1834110c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- 冻结的外键图（迁移不可变；与 scripts/maintenance/orphan_cleanup.py 的
# FK_SPECS、src/models 的 ForeignKey 声明三方一致，由 tests/unit/test_fk_specs.py 机械校验）----
# (child, child_col, parent, parent_col, ondelete, fk_name, index_name|None)
FKS: tuple[tuple[str, str, str, str, str, str, str | None], ...] = (
    # 内容层
    ("articles", "regulation_id", "regulations", "id", "CASCADE",
     "fk_articles_regulation_id", None),
    # 审查链路
    ("review_results", "task_id", "review_tasks", "id", "CASCADE",
     "fk_review_results_task_id", None),
    ("review_results", "rule_id", "rules", "id", "SET NULL",
     "fk_review_results_rule_id", "idx_results_rule_id"),
    ("review_results", "regulation_id", "regulations", "id", "SET NULL",
     "fk_review_results_regulation_id", "idx_results_regulation_id"),
    ("review_results", "article_id", "articles", "id", "SET NULL",
     "fk_review_results_article_id", "idx_results_article_id"),
    ("review_results", "confirmed_by", "users", "id", "SET NULL",
     "fk_review_results_confirmed_by", "idx_results_confirmed_by"),
    # 任务 / 批次
    ("review_tasks", "batch_id", "review_batches", "id", "SET NULL",
     "fk_review_tasks_batch_id", None),
    ("review_tasks", "created_by", "users", "id", "SET NULL",
     "fk_review_tasks_created_by", None),
    ("review_batches", "created_by", "users", "id", "SET NULL",
     "fk_review_batches_created_by", None),
    # 规则-法规关联
    ("rule_regulation_links", "rule_id", "rules", "id", "CASCADE",
     "fk_rule_regulation_links_rule_id", None),
    ("rule_regulation_links", "regulation_id", "regulations", "id", "CASCADE",
     "fk_rule_regulation_links_regulation_id", None),
    ("rule_regulation_links", "article_id", "articles", "id", "SET NULL",
     "fk_rule_regulation_links_article_id", "idx_link_article"),
    ("rule_regulation_links", "created_by", "users", "id", "SET NULL",
     "fk_rule_regulation_links_created_by", "idx_link_created_by"),
    # 签发留痕
    ("task_sign_offs", "task_id", "review_tasks", "id", "CASCADE",
     "fk_task_sign_offs_task_id", None),
    ("task_sign_offs", "user_id", "users", "id", "RESTRICT",
     "fk_task_sign_offs_user_id", "idx_sign_offs_user"),
    # 影响中心
    ("impact_assessments", "regulation_update_id", "regulation_updates", "id", "SET NULL",
     "fk_impact_assessments_reg_update", None),
    ("impact_assessments", "penalty_case_id", "penalty_cases", "id", "SET NULL",
     "fk_impact_assessments_penalty_case", "idx_assessment_penalty"),
    ("impact_assessments", "created_by", "users", "id", "SET NULL",
     "fk_impact_assessments_created_by", "idx_assessment_created_by"),
    ("impact_assessments", "confirmed_by", "users", "id", "SET NULL",
     "fk_impact_assessments_confirmed_by", "idx_assessment_confirmed_by"),
    # 通知 / 审计
    ("notifications", "user_id", "users", "id", "CASCADE",
     "fk_notifications_user_id", None),
    ("audit_logs", "user_id", "users", "id", "SET NULL",
     "fk_audit_logs_user_id", "idx_audit_user"),
)


def _tables() -> list[str]:
    names = {f[0] for f in FKS} | {f[2] for f in FKS}
    return sorted(names)


def _assert_innodb(bind) -> None:
    """前置断言：涉及的表必须全是 InnoDB（MyISAM 不支持外键）。"""
    rows = bind.execute(
        sa.text(
            "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": _tables()},
    ).fetchall()
    bad = [f"{name}({engine})" for name, engine in rows if engine and engine != "InnoDB"]
    if bad:
        raise RuntimeError(f"以下表非 InnoDB，无法建外键：{bad}")


def _align_column_types(bind) -> None:
    """把子列类型对齐到父列（MySQL 外键要求两侧 COLUMN_TYPE 完全一致）。

    见模块 docstring「既有库兼容」：dev 库 signed/unsigned 并存时，直连建 FK
    会报 errno 3780。全新库（迁移链产物）两侧一致 → 本函数为 no-op。
    """
    for child, col, parent, parent_col, _rule, _name, _idx in FKS:
        parent_type = bind.execute(
            sa.text(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
            ),
            {"t": parent, "c": parent_col},
        ).scalar()
        row = bind.execute(
            sa.text(
                "SELECT COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
            ),
            {"t": child, "c": col},
        ).fetchone()
        if not parent_type or not row:
            continue
        child_type, nullable = row
        if child_type == parent_type:
            continue
        null_sql = "NULL" if nullable == "YES" else "NOT NULL"
        print(f"[fk] 类型对齐：{child}.{col} {child_type} → {parent_type}（{null_sql}）")
        bind.execute(sa.text(f"ALTER TABLE `{child}` MODIFY `{col}` {parent_type} {null_sql}"))


def _assert_no_orphans(bind) -> None:
    """前置断言：建 FK 前必须无孤儿行（否则 MySQL 报 errno 1452 半途失败）。

    用可用性优先的口径（与 scripts/maintenance/orphan_cleanup.py 同一张图）：
    `confirmed_by=0`（旧版"系统自动确认"哨兵）也在此被拦——0 不是合法 users.id，
    清洗脚本会把它置空（PR-7 起应用改写 NULL，见 ReviewResult.auto_confirmed）。
    """
    offenders: list[str] = []
    for child, col, parent, parent_col, _rule, _name, _idx in FKS:
        n = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM `{child}` LEFT JOIN `{parent}` "
                f"ON `{child}`.`{col}` = `{parent}`.`{parent_col}` "
                f"WHERE `{child}`.`{col}` IS NOT NULL AND `{parent}`.`{parent_col}` IS NULL"
            )
        ).scalar()
        if n:
            offenders.append(f"{child}.{col}->{parent}.{parent_col}: {n} 行")
    if offenders:
        raise RuntimeError(
            "存在孤儿行，无法建外键（先执行前置清洗）：\n  "
            + "\n  ".join(offenders)
            + "\n修复：python scripts/maintenance/orphan_cleanup.py --apply"
        )


def _create_fk(idx: int) -> None:
    child, col, parent, parent_col, rule, name, index_name = FKS[idx]
    if index_name:
        op.create_index(index_name, child, [col])
    op.create_foreign_key(name, child, parent, [col], [parent_col], ondelete=rule)


def _drop_fk(idx: int) -> None:
    child, _col, _parent, _parent_col, _rule, name, index_name = FKS[idx]
    op.drop_constraint(name, child, type_="foreignkey")
    if index_name:
        op.drop_index(index_name, table_name=child)


# ---- 一张表一个迁移函数（便于按表回滚/审阅）----
def _articles() -> None:
    _create_fk(0)


def _review_results() -> None:
    for i in (1, 2, 3, 4, 5):
        _create_fk(i)


def _review_tasks() -> None:
    _create_fk(6)
    _create_fk(7)


def _review_batches() -> None:
    _create_fk(8)


def _rule_regulation_links() -> None:
    for i in (9, 10, 11, 12):
        _create_fk(i)


def _task_sign_offs() -> None:
    _create_fk(13)
    _create_fk(14)


def _impact_assessments() -> None:
    for i in (15, 16, 17, 18):
        _create_fk(i)


def _notifications() -> None:
    _create_fk(19)


def _audit_logs() -> None:
    _create_fk(20)


_TABLE_FUNCS = (
    _articles,
    _review_results,
    _review_tasks,
    _review_batches,
    _rule_regulation_links,
    _task_sign_offs,
    _impact_assessments,
    _notifications,
    _audit_logs,
)


def upgrade() -> None:
    bind = op.get_bind()
    _assert_innodb(bind)
    _assert_no_orphans(bind)
    _align_column_types(bind)
    for func in _TABLE_FUNCS:
        func()


def downgrade() -> None:
    # 逆序逐条拆（先外键后索引；表间无级联依赖，逆序仅为可读性）
    for i in reversed(range(len(FKS))):
        _drop_fk(i)
