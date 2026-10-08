from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("idx_article_no", "regulation_id", "article_no"),
        Index("idx_regulation_id", "regulation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    regulation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chapter_no: Mapped[str | None] = mapped_column(String(64))  # 章
    section_no: Mapped[str | None] = mapped_column(String(16))  # 节
    article_no: Mapped[str | None] = mapped_column(String(16))  # 条，如：第二十六条
    clause_no: Mapped[str | None] = mapped_column(String(16))   # 款
    item_no: Mapped[str | None] = mapped_column(String(16))     # 项
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(64))   # 向量库中的 ID
