from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ProductMaterial(Base):
    """产品材料台账（公开监管数据 + 模拟业务台账，README 已标注）。

    台账条目通过 document_id 关联上传的待审文档，
    影响评估据此定位受影响的存量材料并创建批量复审。
    """

    __tablename__ = "product_materials"
    __table_args__ = (Index("idx_material_product", "product_type", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type: Mapped[str] = mapped_column(String(32), nullable=False)  # fund/insurance/wealth
    material_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 单页/海报/推文/话术稿
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    owner: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(String(64))  # doc_xxxxxxxx
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_review_status: Mapped[str | None] = mapped_column(String(16))  # clean/violation/failed
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # R3 发布后监控：已发布渠道与内容指纹（巡检基线 = 批准版规范化文本）
    publish_url: Mapped[str | None] = mapped_column(String(512))
    channel: Mapped[str | None] = mapped_column(String(32))  # web/wechat/douyin
    # 批准版规范化文本（相似度比对基线）
    content_fingerprint: Mapped[str | None] = mapped_column(Text)
    patrol_status: Mapped[str | None] = mapped_column(String(16))  # ok/drift/changed/gone/error
    patrol_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
