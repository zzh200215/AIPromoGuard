from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ReviewResult(Base):
    __tablename__ = "review_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    violation_type: Mapped[str] = mapped_column(String(16), nullable=False)  # rule/llm/hybrid
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, default="low")
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    location_page: Mapped[int | None] = mapped_column(Integer)
    location_paragraph: Mapped[int | None] = mapped_column(Integer)
    regulation_id: Mapped[int | None] = mapped_column(BigInteger)
    article_id: Mapped[int | None] = mapped_column(BigInteger)
    rule_id: Mapped[int | None] = mapped_column(BigInteger)
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0")
    )
    description: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_confirm")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
