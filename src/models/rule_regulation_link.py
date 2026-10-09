from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class RuleRegulationLink(Base):
    """规则与法规条款的标准化关联。

    规则的合规依据不再只写在 rule_content/description 文本里，
    而是结构化挂到具体法规（或条款），影响分析据此按条款反查受影响规则。
    """

    __tablename__ = "rule_regulation_links"
    __table_args__ = (
        Index("idx_link_rule", "rule_id"),
        Index("idx_link_regulation", "regulation_id"),
        # PR-7：外键列索引显式化
        Index("idx_link_article", "article_id"),
        Index("idx_link_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 关联行强从属于规则与法规（任一被删则该关联无意义）；条款/创建人为弱引用
    rule_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("rules.id", ondelete="CASCADE", name="fk_rule_regulation_links_rule_id"),
        nullable=False,
    )
    regulation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "regulations.id", ondelete="CASCADE", name="fk_rule_regulation_links_regulation_id"
        ),
    )
    article_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="SET NULL", name="fk_rule_regulation_links_article_id"),
    )
    citation: Mapped[str | None] = mapped_column(String(255))  # 引用文本
    link_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="support", server_default="support"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_rule_regulation_links_created_by"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
