"""站内通知：关键事件（任务失败/批次终态）触达责任人，避免只靠盯页面。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_user", "user_id", "is_read"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 接收人；通知按用户隔离，不跨部门可见（用户删则通知随之删）
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE", name="fk_notifications_user_id"),
        nullable=False,
    )
    # task_failed / batch_completed / batch_failed（后续可扩展整改到期等）
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(String(512))
    # 前端跳转路径，如 /tasks/15、/batches/2
    link: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[int] = mapped_column(TINYINT, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
