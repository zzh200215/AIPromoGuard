from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ReviewResult(Base):
    __tablename__ = "review_results"
    __table_args__ = (
        Index("idx_status", "status"),
        Index("idx_task_id", "task_id"),
        # PR-7：外键列索引显式化（FK 必需；显式命名避免 MySQL 自动命名漂移）
        Index("idx_results_rule_id", "rule_id"),
        Index("idx_results_regulation_id", "regulation_id"),
        Index("idx_results_article_id", "article_id"),
        Index("idx_results_confirmed_by", "confirmed_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # PR-7 外键：结果强从属于任务（任务删则结论无意义）；规则/法规/条款/复核人为
    # 弱引用（法规废止后历史结论仍需保留，故 SET NULL 而非删行）
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_tasks.id", ondelete="CASCADE", name="fk_review_results_task_id"),
        nullable=False,
    )
    violation_type: Mapped[str] = mapped_column(String(16), nullable=False)  # rule/llm/hybrid
    risk_level: Mapped[str] = mapped_column(
        String(8), nullable=False, default="low", server_default="low"
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    location_page: Mapped[int | None] = mapped_column(Integer)
    location_paragraph: Mapped[int | None] = mapped_column(Integer)
    regulation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("regulations.id", ondelete="SET NULL", name="fk_review_results_regulation_id"),
    )
    article_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="SET NULL", name="fk_review_results_article_id"),
    )
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("rules.id", ondelete="SET NULL", name="fk_review_results_rule_id"),
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0"), server_default="0.000"
    )
    description: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending_confirm", server_default="pending_confirm"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_review_results_confirmed_by"),
    )

    @property
    def auto_confirmed(self) -> bool:
        """系统自动确认（方向②分流）：已判违规、但无人工 actor。

        PR-7：原哨兵值 0（"系统自动"）与外键冲突（0 不是合法 users.id），
        改用 NULL 表达"无 actor"——人工确认一定写入真实 user id（API 强制），
        故 `status='confirmed' 且 confirmed_by 为空` ⇔ 系统自动确认。
        """
        return self.status == "confirmed" and self.confirmed_by is None
