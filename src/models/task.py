from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("idx_batch_id", "batch_id"),
        Index("idx_created_by", "created_by"),
        Index("idx_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_path: Mapped[str | None] = mapped_column(String(512))
    document_type: Mapped[str | None] = mapped_column(String(32))
    domain: Mapped[str | None] = mapped_column(String(32))
    # 审查策略 strict/standard/loose（NULL=standard）
    profile: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    progress: Mapped[int] = mapped_column(TINYINT, default=0, server_default="0", nullable=False)
    stages: Mapped[dict | None] = mapped_column(JSON)  # 各 Agent 节点状态/耗时（PRD §11.3）
    llm_usage: Mapped[dict | None] = mapped_column(JSON)  # LLM token 用量/预估成本（成本归因）
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_review_tasks_created_by")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    report_path: Mapped[str | None] = mapped_column(String(512))
    batch_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("review_batches.id", ondelete="SET NULL", name="fk_review_tasks_batch_id"),
    )
    base_document_name: Mapped[str | None] = mapped_column(String(255))
    base_document_path: Mapped[str | None] = mapped_column(String(512))
    diff_changes: Mapped[dict | None] = mapped_column(JSON)  # 对比审查变更片段
