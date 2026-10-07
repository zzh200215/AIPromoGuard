"""审核签发记录：报告定稿后的正式放行/驳回动作（合规闭环）。

一个任务允许多次签发（改签留痕），最新一次为有效结论；报告读取/导出时
取最新记录合并进 sign_off 块。签发门槛：任务已完成且待复核清零。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class TaskSignOff(Base):
    __tablename__ = "task_sign_offs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # released = 同意放行；rejected = 驳回整改
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
