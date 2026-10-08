from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class RegulationUpdate(Base):
    """监管动态追踪：抓取到的待确认法规条目。"""

    __tablename__ = "regulation_updates"
    __table_args__ = (UniqueConstraint("source", "title", name="uk_source_title"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # nfra/csrc/pbc
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_no: Mapped[str | None] = mapped_column(String(64))  # 文号
    publish_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(String(512))
    domain: Mapped[str | None] = mapped_column(String(32))  # LLM 判定，banking/fund/insurance/other
    doc_type: Mapped[str | None] = mapped_column(String(32))  # 规章/规范性文件/办法/公告
    llm_summary: Mapped[str | None] = mapped_column(String(512))
    matched_regulations: Mapped[dict | None] = mapped_column(JSON)  # 匹配的库内法规
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    match_type: Mapped[str | None] = mapped_column(String(16))  # fetch/confirm/manual/in_db
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
