"""法规影响中心闭环服务：复审批次终态 → 回写材料台账 + 生成整改清单。

整改清单存于 ImpactAssessment.items["remediation"]，按 task_id 幂等合并；
人工决策（remediate/reject/done）由 API 层写入并留审计。
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.models import ImpactAssessment, ProductMaterial, ReviewBatch, ReviewResult, ReviewTask
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _doc_id_from_path(path: str | None) -> str | None:
    """document_path → doc_xxxxxxxx（文件名去扩展名）。"""
    if not path:
        return None
    stem = Path(path).stem
    return stem if stem.startswith("doc_") else None


def sync_batch_to_assessment(db: Session, batch_id: int) -> None:
    """批次终态后回写影响评估：更新材料最近审查状态并生成整改清单。

    仅处理 source_type=impact_assessment 的批次；按 task_id 幂等，
    重复调用不产生重复条目（但会覆盖未决策的 pending 状态计数）。
    """
    # 结束调用方遗留的读事务快照（REPEATABLE READ 下旧快照会看不到
    # 并行人工决策，进而把 pending 写回去覆盖它）
    db.rollback()
    batch = db.get(ReviewBatch, batch_id)
    if batch is None or batch.source_type != "impact_assessment" or batch.source_id is None:
        return
    assessment = db.get(ImpactAssessment, batch.source_id)
    if assessment is None:
        logger.warning("批次 %s 溯源的评估 %s 不存在，跳过回写", batch_id, batch.source_id)
        return

    tasks = db.query(ReviewTask).filter(ReviewTask.batch_id == batch_id).all()
    violation_counts = dict(
        db.query(ReviewResult.task_id, func.count(ReviewResult.id))
        .filter(ReviewResult.task_id.in_([t.id for t in tasks] or [0]))
        .group_by(ReviewResult.task_id)
        .all()
    )

    remediation = []
    for task in tasks:
        doc_id = _doc_id_from_path(task.document_path)
        material = (
            db.query(ProductMaterial).filter_by(document_id=doc_id).one_or_none()
            if doc_id
            else None
        )
        violations = int(violation_counts.get(task.id, 0))
        if task.status == "completed":
            review_status = "violation" if violations else "clean"
        else:
            review_status = "failed"
        if material is not None:
            material.last_review_status = review_status
            material.last_reviewed_at = datetime.now()
        remediation.append(
            {
                "batch_id": batch_id,
                "task_id": task.id,
                "task_status": task.status,
                "material_id": material.id if material else None,
                "material_name": material.name if material else task.task_name,
                "violation_count": violations,
                "requires_remediation": violations > 0 and task.status == "completed",
                "decision": "pending",  # pending/remediate/reject/done
            }
        )

    items = assessment.items or {}
    merged = {entry["task_id"]: entry for entry in items.get("remediation") or []}
    for entry in remediation:
        old = merged.get(entry["task_id"])
        # 已人工决策的条目保留决策，仅刷新审查侧字段
        if old and old.get("decision") not in (None, "pending"):
            old.update(
                {k: v for k, v in entry.items() if k != "decision"}
            )
            merged[entry["task_id"]] = old
        else:
            merged[entry["task_id"]] = entry
    items["remediation"] = list(merged.values())
    assessment.items = items
    flag_modified(assessment, "items")  # JSON 原地改需显式标脏
    db.commit()
    logger.info(
        "批次 %s 回写评估 %s：%d 条整改项", batch_id, assessment.id, len(items["remediation"])
    )


def decide_remediation(
    db: Session, assessment_id: int, task_id: int, decision: str
) -> list[dict]:
    """记录人工整改决策（remediate/reject/done），返回最新整改清单。"""
    assessment = db.get(ImpactAssessment, assessment_id)
    if assessment is None:
        raise KeyError("影响评估不存在")
    items = assessment.items or {}
    remediation = items.get("remediation") or []
    entry = next((e for e in remediation if e.get("task_id") == task_id), None)
    if entry is None:
        raise KeyError(f"整改项 task_id={task_id} 不存在")
    entry["decision"] = decision
    items["remediation"] = remediation
    assessment.items = items
    flag_modified(assessment, "items")
    db.commit()
    return remediation
