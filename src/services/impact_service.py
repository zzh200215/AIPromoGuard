"""法规影响中心闭环服务：复审批次终态 → 回写材料台账 + 生成整改清单 + 整改复测。

整改清单存于 ImpactAssessment.items["remediation"]，按 task_id 幂等合并；
人工决策（remediate/reject/done）由 API 层写入并留审计。整改复测走单任务
复审批次回挂原评估，复测通过（零违规）时原整改项自动标记 done。
"""

import re
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

    # 原整改项记录的复测任务 → 新条目带 retest 标记并回指原任务
    retest_map = {
        e["retest_task_id"]: e["task_id"]
        for e in (assessment.items or {}).get("remediation") or []
        if e.get("retest_task_id")
    }

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
        entry = {
            "batch_id": batch_id,
            "task_id": task.id,
            "task_status": task.status,
            "material_id": material.id if material else None,
            "material_name": material.name if material else task.task_name,
            "violation_count": violations,
            "requires_remediation": violations > 0 and task.status == "completed",
            "decision": "pending",  # pending/remediate/reject/done
        }
        if task.id in retest_map:
            entry["retest"] = True
            entry["retest_for_task_id"] = retest_map[task.id]
        remediation.append(entry)

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

    # 整改复测闭环：复测通过（completed 且零违规）→ 原整改项自动标记 done；
    # 仍违规则保持原状，新条目本身就是新的整改项
    for entry in items["remediation"]:
        if not entry.get("retest"):
            continue
        retest_clean = (
            entry.get("task_status") == "completed" and entry.get("violation_count") == 0
        )
        if retest_clean:
            orig = next(
                (
                    e
                    for e in items["remediation"]
                    if e.get("retest_task_id") == entry["task_id"]
                ),
                None,
            )
            if orig and orig.get("decision") in (None, "pending", "remediate"):
                orig["decision"] = "done"
            if entry.get("decision") in (None, "pending"):
                entry["decision"] = "done"

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


def _next_version(version: str | None) -> str:
    m = re.fullmatch(r"v(\d+)", (version or "").strip())
    return f"v{int(m.group(1)) + 1}" if m else "v2"


def start_retest(
    db: Session,
    assessment: ImpactAssessment,
    material: ProductMaterial,
    document_path: str,
    document_id: str,
    user_id: int | None,
) -> dict:
    """发起整改复测：材料升版挂新文档，单任务复审批次回挂原评估。

    批次沿用 source_type=impact_assessment 的既有回写链路——终态后
    sync_batch_to_assessment 生成带 retest 标记的新条目，复测通过时
    自动关闭原整改项并回写台账 clean。
    """
    items = assessment.items or {}
    orig = next(
        (
            e
            for e in items.get("remediation") or []
            if e.get("material_id") == material.id
            and e.get("requires_remediation")
            and e.get("decision") != "done"
        ),
        None,
    )
    if orig is None:
        raise KeyError("该材料没有待整改项，无需复测")

    material.version = _next_version(material.version)
    material.document_id = document_id

    batch = ReviewBatch(
        batch_name=f"整改复测：{material.name}"[:255],
        total_count=1,
        created_by=user_id,
        source_type="impact_assessment",
        source_id=assessment.id,
    )
    db.add(batch)
    db.flush()
    task = ReviewTask(
        task_name=f"整改复测 {material.name}",
        document_name=Path(document_path).name,
        document_path=str(document_path),
        status="pending",
        created_by=user_id,
        batch_id=batch.id,
    )
    db.add(task)
    db.flush()
    orig["retest_task_id"] = task.id  # sync 侧据此生成 retest 条目与自动闭环
    flag_modified(assessment, "items")
    db.commit()

    from src.services.review_service import start_review

    start_review(task.id)
    logger.info(
        "评估 %s 材料 %s 整改复测启动：task %s（%s → %s）",
        assessment.id,
        material.name,
        task.id,
        document_path,
        material.version,
    )
    return {"batch_id": batch.id, "task_id": task.id, "version": material.version}


def stale_materials_check(db: Session, limit: int = 50) -> dict:
    """时效性告警（R3-2）：规则停用 / 法规废止 反向定位受影响的在用材料.

    关联链（全为既有数据，不新增表）：material.document_id → 审查任务
    （document_name = doc_id.ext）→ results.rule_id → 规则停用状态；
    规则 → rule_regulation_link → 法规 status（effective 之外的视为失效）。

    只读查询，不写任何状态——产出"待更新"清单挂驾驶舱，人工据此走
    影响分析/整改流程（与 R3-1 的 changed 自动复审互补：那边抓线上内容
    被改，这边抓依据失效）。
    """
    from src.models import Regulation, Rule, RuleRegulationLink

    inactive_rules = {
        r.id: f"规则已停用：{r.rule_name}"
        for r in db.query(Rule).filter(Rule.is_active == 0).all()
    }
    inactive_regs = {
        r.id: f"法规已废止/失效：{r.regulation_name}"
        for r in db.query(Regulation).filter(Regulation.status != "effective").all()
    }
    rule_to_reg = {
        link.rule_id: link.regulation_id
        for link in db.query(RuleRegulationLink).all()
        if link.regulation_id
    }

    materials = (
        db.query(ProductMaterial)
        .filter(ProductMaterial.status == "active")
        .order_by(ProductMaterial.id)
        .all()
    )
    stale = []
    for m in materials:
        # rule_ids 收集：material.document_id → 审查任务 → results
        rule_ids: set[int] = set()
        if m.document_id:
            tasks = (
                db.query(ReviewTask)
                .filter(ReviewTask.document_name.like(f"{m.document_id}.%"))
                .all()
            )
            for t in tasks:
                rows = (
                    db.query(ReviewResult)
                    .filter(
                        ReviewResult.task_id == t.id,
                        ReviewResult.rule_id.isnot(None),
                    )
                    .all()
                )
                rule_ids.update(r.rule_id for r in rows if r.rule_id)
        reasons = material_stale_reasons(rule_ids, inactive_rules, inactive_regs, rule_to_reg)
        if reasons:
            stale.append(
                {
                    "material_id": m.id,
                    "name": m.name,
                    "version": m.version,
                    "last_review_status": m.last_review_status,
                    "reasons": reasons,
                }
            )
            if len(stale) >= limit:
                break
    return {
        "checked": len(materials),
        "stale_count": len(stale),
        "materials": stale,
    }


def material_stale_reasons(
    rule_ids: set[int],
    inactive_rules: dict[int, str],
    inactive_regs: dict[int, str],
    rule_to_reg: dict[int, int],
) -> list[str]:
    """时效判定纯函数：命中的规则里，停用规则或其关联法规失效即为待更新。"""
    reasons: list[str] = []
    for rid in sorted(rule_ids):
        if rid in inactive_rules:
            reasons.append(inactive_rules[rid])
        elif rid in rule_to_reg and rule_to_reg[rid] in inactive_regs:
            reasons.append(inactive_regs[rule_to_reg[rid]])
    return reasons
