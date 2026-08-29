from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class LlmCache(Base):
    """LLM 精确匹配响应缓存（P5，workflow.llm_cache 开启时写入）。

    key_hash 覆盖 (schema 版本, 模型, 温度, json_mode, messages)；命中即跳过
    网络调用。TTL 到期由查询侧过滤 + 清理脚本删除。
    """

    __tablename__ = "llm_cache"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[dict | None] = mapped_column(JSON)
    hits: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
