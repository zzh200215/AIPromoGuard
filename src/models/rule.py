from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # regex/keyword/condition/composite
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_content: Mapped[dict] = mapped_column(JSON, nullable=False)  # 规则 DSL
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    description: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[int] = mapped_column(default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
