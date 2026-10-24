from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class CopilotMessage(Base):
    """审查问答 Copilot 的会话历史（多轮记忆的最小可见落点）。

    一个任务一个会话线程（task_id 唯一定位），user/assistant 交替落库；
    ask_review_question 每轮携带最近 N 条历史构建上下文，回答可指代
    "上一条说的第 3 条违规"——从单次问答升级为可追问的对话。
    """

    __tablename__ = "copilot_messages"
    __table_args__ = (
        Index("idx_copilot_messages_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_tasks.id", ondelete="CASCADE", name="fk_copilot_messages_task_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # assistant 轮的法规引用（JSON 数组，user 轮为 NULL）
    refs_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
