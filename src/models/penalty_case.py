from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class PenaltyCase(Base):
    __tablename__ = "penalty_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_name: Mapped[str] = mapped_column(String(255), nullable=False)
    penalty_org: Mapped[str | None] = mapped_column(String(128))  # 处罚机构
    penalty_date: Mapped[date | None] = mapped_column(Date)
    penalty_result: Mapped[str | None] = mapped_column(String(512))
    violation_summary: Mapped[str | None] = mapped_column(Text)
    related_regulations: Mapped[list | None] = mapped_column(JSON)  # 关联法规 id 数组
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
