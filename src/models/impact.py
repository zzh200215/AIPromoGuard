from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class ImpactAssessment(Base):
    """法规/处罚事件影响评估（法规影响中心核心表）。

    一次监管事件（新规或罚单）触发一次评估，明细以 JSON 存储：
    {"rules": [{rule_id, rule_name, reason, confirm_status}],
     "materials": [{material_id, name, reason, risk_level, evidence, confirm_status}]}
    状态机 draft → pending_review → confirmed/dismissed；
    复审批次通过 review_batches.source_type='impact_assessment' 反向挂回，本表不存批次。
    """

    __tablename__ = "impact_assessments"
    __table_args__ = (
        Index("idx_assessment_status", "status"),
        Index("idx_assessment_update", "regulation_update_id"),
        # PR-7：外键列索引显式化
        Index("idx_assessment_penalty", "penalty_case_id"),
        Index("idx_assessment_created_by", "created_by"),
        Index("idx_assessment_confirmed_by", "confirmed_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 触发源为弱引用：监管动态/处罚案例被清理后，评估记录本身仍需保留（SET NULL）
    regulation_update_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "regulation_updates.id", ondelete="SET NULL", name="fk_impact_assessments_reg_update"
        ),
    )  # 触发源：监管动态
    penalty_case_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "penalty_cases.id", ondelete="SET NULL", name="fk_impact_assessments_penalty_case"
        ),
    )  # 触发源：处罚案例（二选一）
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )  # draft/pending_review/confirmed/dismissed
    items: Mapped[dict | None] = mapped_column(JSON)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    medium_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_impact_assessments_created_by"),
    )
    confirmed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_impact_assessments_confirmed_by"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
