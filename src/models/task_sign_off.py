"""审核签发记录：报告定稿后的正式放行/驳回动作（合规闭环）。

一个任务允许多次签发（改签留痕），最新一次为有效结论；报告读取/导出时
取最新记录合并进 sign_off 块。签发门槛：任务已完成且待复核清零。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class TaskSignOff(Base):
    __tablename__ = "task_sign_offs"
    __table_args__ = (
        Index("idx_task_sign_offs_task", "task_id"),
        # PR-7：签字人外键列索引显式化
        Index("idx_sign_offs_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 强从属：任务删除则签发留痕无意义
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_tasks.id", ondelete="CASCADE", name="fk_task_sign_offs_task_id"),
        nullable=False,
    )
    # 签字人 RESTRICT：签发是审计证据，有签字记录的用户不允许硬删除
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_task_sign_offs_user_id"),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # released = 同意放行；rejected = 驳回整改
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
