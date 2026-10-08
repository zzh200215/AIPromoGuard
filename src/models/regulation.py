from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class Regulation(Base):
    __tablename__ = "regulations"
    __table_args__ = (Index("idx_domain", "domain"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)  # banking/fund/insurance
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    regulation_no: Mapped[str | None] = mapped_column(String(64))  # 文号
    issuer: Mapped[str | None] = mapped_column(String(128))
    publish_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="effective", server_default="effective"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
