"""add precedent memory (review_precedents + copilot_messages)

Revision ID: a7c4f1e9b3d2
Revises: 1d7ed1680920
Create Date: 2026-10-24 11:30:00.000000

第 2 批能力「判定先例记忆」的两张新表：

- **review_precedents**：人工复核终态结论（confirmed / false_positive，
  confirmed_by>0）的先例沉淀。一个 result 至多一条（uq_precedents_result_id），
  判定翻转 upsert 覆盖、撤销复核删除——记忆始终等于最新人工判断。
  外键沿用 PR-7 纪律：result/task 强从属 CASCADE；rule / 复核人弱引用 SET NULL。
- **copilot_messages**：审查问答 Copilot 的多轮会话历史（task 强从属 CASCADE），
  ask_review_question 每轮携带最近 N 条历史构建上下文。

回滚对称：downgrade 直接 drop 两表（先例/会话为可再生数据，
源数据 review_results.review_tasks 保留）。
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4f1e9b3d2"
down_revision: str | None = "1d7ed1680920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 本迁移创建的外键注册表——与 orphan_cleanup.py::FK_SPECS 同一张图的冻结副本，
# 由 tests/unit/test_fk_specs.py 聚合全部迁移的 FKS 做三方一致性校验。
# 字段：(child_table, child_col, parent_table, parent_col, ondelete, fk_name, extra)
FKS: tuple[tuple[str, str, str, str, str, str, str | None], ...] = (
    ("review_precedents", "result_id", "review_results", "id", "CASCADE",
     "fk_precedents_result_id", None),
    ("review_precedents", "task_id", "review_tasks", "id", "CASCADE",
     "fk_precedents_task_id", None),
    ("review_precedents", "rule_id", "rules", "id", "SET NULL",
     "fk_precedents_rule_id", None),
    ("review_precedents", "confirmed_by", "users", "id", "SET NULL",
     "fk_precedents_confirmed_by", None),
    ("copilot_messages", "task_id", "review_tasks", "id", "CASCADE",
     "fk_copilot_messages_task_id", None),
)


def upgrade() -> None:
    op.create_table(
        "review_precedents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("result_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("violation_type", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.BigInteger(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("document_name", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=32), nullable=True),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["result_id"], ["review_results.id"], name="fk_precedents_result_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["review_tasks.id"], name="fk_precedents_task_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["rules.id"], name="fk_precedents_rule_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_precedents_confirmed_by", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_id", name="uq_precedents_result_id"),
    )
    op.create_index("idx_precedents_task_id", "review_precedents", ["task_id"], unique=False)
    op.create_index("idx_precedents_verdict", "review_precedents", ["verdict"], unique=False)

    op.create_table(
        "copilot_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("refs_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["review_tasks.id"], name="fk_copilot_messages_task_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_copilot_messages_task_id", "copilot_messages", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_copilot_messages_task_id", table_name="copilot_messages")
    op.drop_table("copilot_messages")
    op.drop_index("idx_precedents_verdict", table_name="review_precedents")
    op.drop_index("idx_precedents_task_id", table_name="review_precedents")
    op.drop_table("review_precedents")
