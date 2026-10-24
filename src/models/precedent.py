from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ReviewPrecedent(Base):
    """判定先例记忆（第 2 批能力）：人工复核终态结论的沉淀与复用载体。

    写入源：人工对 review_results 的 confirmed / false_positive 判定
    （confirmed_by>0 的真实人工结论，天然满足数据卫生铁律——系统自动
    确认不沉淀，避免循环论证）。一个 result 至多一条最新先例：判定翻转
    时 upsert 覆盖，撤销复核时删除——记忆始终与最新人工判断一致。

    用途：审查时按相似度召回同类先例注入 LLM 审查上下文
    （precedent_memory.recall_precedents），误报先例校准"宁缺毋滥"的
    边界、确认先例提示本机构的真实风险模式——系统开始从人工纠正中学习。
    """

    __tablename__ = "review_precedents"
    __table_args__ = (
        UniqueConstraint("result_id", name="uq_precedents_result_id"),
        Index("idx_precedents_task_id", "task_id"),
        Index("idx_precedents_verdict", "verdict"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 先例强从属于结论与任务（结论/任务删除则先例无意义）；复核人为弱引用
    result_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_results.id", ondelete="CASCADE", name="fk_precedents_result_id"),
        nullable=False,
    )
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_tasks.id", ondelete="CASCADE", name="fk_precedents_task_id"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # confirmed | false_positive
    violation_type: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("rules.id", ondelete="SET NULL", name="fk_precedents_rule_id"),
    )
    # 召回语义载体：违规原文片段 + 问题描述（embedding 以此两字段拼接）
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    issue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_name: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(32))
    confirmed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_precedents_confirmed_by"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
