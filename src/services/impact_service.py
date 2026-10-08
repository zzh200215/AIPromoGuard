"""法规影响中心闭环服务：复审批次终态 → 回写材料台账 + 生成整改清单 + 整改复测。

整改清单存于 ImpactAssessment.items["remediation"]，按 task_id 幂等合并；
人工决策（remediate/reject/done）由 API 层写入并留审计。整改复测走单任务
复审批次回挂原评估，复测通过（零违规）时原整改项自动标记 done。

R3-2 v2（2026-10-07）：依据失效材料（规则停用/法规废止反向定位）经
sync_stale_to_assessment 写入系统单例容器评估的整改清单（条目 kind="stale"，
无审查任务、按 material_id 定位），与审查产生的整改项共用决策/复测/自动
关闭链路——两类条目以命名空间前缀区分（_entry_key）。
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


# 系统单例容器评估的标题（R3-2 v2）：无触发源、状态 confirmed，
# 承载依据失效材料的"待更新"整改项——语义上就是"规则停用/法规废止 → 反向影响材料"
STALE_CONTAINER_TITLE = "时效性告警：依据失效待更新材料"


def _entry_key(entry: dict) -> str:
    """整改条目定位键：审查条目按 task_id；待更新条目（stale）按 material_id。

    两类条目共处同一 remediation 列表，合并时用命名空间前缀区分——
    否则 stale 条目缺少 task_id 会让字典推导 KeyError（复测回写时必现）。
    """
    if entry.get("task_id"):
        return f"task:{entry['task_id']}"
    return f"stale:{entry.get('material_id')}"


def get_or_create_stale_container(db: Session) -> ImpactAssessment:
    """系统单例容器评估：承载依据失效材料的"待更新"整改项（幂等）。"""
    container = (
        db.query(ImpactAssessment)
        .filter(ImpactAssessment.title == STALE_CONTAINER_TITLE)
        .first()
    )
    if container is not None:
        return container
    container = ImpactAssessment(
        title=STALE_CONTAINER_TITLE,
        summary="系统自动维护：规则停用/法规废止反向定位的在用材料，决策后走既有整改复测链闭环",
        status="confirmed",
        items={"remediation": []},
    )
    db.add(container)
    db.commit()
    db.refresh(container)
    logger.info("创建时效性告警容器评估 %s", container.id)
    return container


def merge_stale_entries(remediation: list[dict], stale_materials: list[dict]) -> dict:
    """纯函数：把失效材料合并进整改清单（原地修改 remediation），返回增量统计。

    幂等规则（按 material_id 定位 kind="stale" 条目）：
    - 新失效材料 → 追加 pending 条目；
    - 仍失效 → 刷新原因/版本/台账状态，保留人工决策；
    - 依据恢复（不在本次失效清单）→ pending/整改中条目自动关闭并留 resolved 说明；
      人工已驳回（reject）或已通过复测关闭（done 且无 resolved 标记）的不动；
    - 靠"依据恢复"被系统关闭的条目再次失效 → 重新置 pending（自愈）。
    """
    by_material = {
        e.get("material_id"): e for e in remediation if e.get("kind") == "stale"
    }
    counts = {"added": 0, "refreshed": 0, "resolved": 0, "reopened": 0}
    stale_ids: set[int] = set()

    for m in stale_materials:
        mid = m["material_id"]
        stale_ids.add(mid)
        entry = by_material.get(mid)
        if entry is None:
            remediation.append(
                {
                    "kind": "stale",
                    "material_id": mid,
                    "material_name": m["name"],
                    "version": m.get("version"),
                    "last_review_status": m.get("last_review_status"),
                    "reasons": m["reasons"],
                    "requires_remediation": True,
                    "decision": "pending",
                }
            )
            counts["added"] += 1
            continue
        entry["material_name"] = m["name"]
        entry["version"] = m.get("version")
        entry["last_review_status"] = m.get("last_review_status")
        if entry.get("reasons") != m["reasons"]:
            entry["reasons"] = m["reasons"]
            counts["refreshed"] += 1
        if entry.get("decision") == "done" and entry.get("resolved"):
            entry["decision"] = "pending"
            entry.pop("resolved", None)
            entry.pop("resolved_at", None)
            counts["reopened"] += 1

    for entry in [e for e in remediation if e.get("kind") == "stale"]:
        if entry.get("material_id") in stale_ids:
            continue
        if entry.get("decision") in (None, "pending", "remediate"):
            entry["decision"] = "done"
            entry["resolved"] = "依据已恢复（规则重新启用/法规状态更新）"
            entry["resolved_at"] = datetime.now().isoformat(timespec="seconds")
            counts["resolved"] += 1

    return counts


def _stale_state_snapshot(remediation: list[dict]) -> dict[int, tuple]:
    """同步前快照：stale 条目的 (决策, 原因清单)，用于识别本轮被触动的条目。"""
    return {
        e["material_id"]: (e.get("decision"), tuple(e.get("reasons") or []))
        for e in remediation
        if e.get("kind") == "stale" and e.get("material_id") is not None
    }


def stale_touched_ids(before: dict[int, tuple], remediation: list[dict]) -> list[int]:
    """本轮同步新增/刷新/重开的 stale 待办条目 id（前端整改清单高亮用）。

    「被触动」= 同步前不存在（新增）或 (决策, 原因) 发生变化（刷新/重开）；
    已被系统关闭（依据恢复）或人工关闭的条目不返回——高亮只指向仍需处理的行。
    """
    touched: list[int] = []
    for e in remediation:
        if e.get("kind") != "stale" or e.get("material_id") is None:
            continue
        mid = e["material_id"]
        state = (e.get("decision"), tuple(e.get("reasons") or []))
        if before.get(mid) == state:
            continue
        if e.get("decision") in ("pending", "remediate"):
            touched.append(mid)
    return touched


def sync_stale_to_assessment(db: Session) -> dict:
    """写入"待更新"整改项（R3-2 v2）：依据失效材料合并进系统容器的整改清单。

    复用 stale_materials_check 只读查询 + merge_stale_entries 纯函数；
    结果落容器评估，人工决策与整改复测走既有链路（见模块 docstring）。
    响应携带 highlight_ids（本轮新增/刷新/重开的待办条目），供前端高亮。
    """
    summary = stale_materials_check(db)
    container = get_or_create_stale_container(db)
    items = container.items or {}
    remediation: list[dict] = items.get("remediation") or []

    before = _stale_state_snapshot(remediation)
    counts = merge_stale_entries(remediation, summary["materials"])
    highlight_ids = stale_touched_ids(before, remediation)

    items["remediation"] = remediation
    container.items = items
    flag_modified(container, "items")
    db.commit()
    logger.info(
        "时效性告警同步：新增 %s / 刷新 %s / 关闭 %s / 重开 %s（共 %s 条）",
        counts["added"],
        counts["refreshed"],
        counts["resolved"],
        counts["reopened"],
        len(remediation),
    )
    return {
        "assessment_id": container.id,
        "checked": summary["checked"],
        "stale_count": summary["stale_count"],
        "total": len(remediation),
        "highlight_ids": highlight_ids,
        **counts,
    }


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
    # （原条目可能是 stale 待更新项：无 task_id，回指留空由 material 侧兜底）
    retest_map = {
        e["retest_task_id"]: e.get("task_id")
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
            if retest_map[task.id]:  # 原条目为 stale 待更新项时无 task_id，不设回指
                entry["retest_for_task_id"] = retest_map[task.id]
        remediation.append(entry)

    items = assessment.items or {}
    # 合并键按命名空间区分（task:{id} / stale:{material_id}）——容器里可能
    # 同时存在审查整改项与 R3-2 的 stale 待更新项，后者无 task_id
    merged = {_entry_key(entry): entry for entry in items.get("remediation") or []}
    for entry in remediation:
        key = _entry_key(entry)
        old = merged.get(key)
        # 已人工决策的条目保留决策，仅刷新审查侧字段
        if old and old.get("decision") not in (None, "pending"):
            old.update(
                {k: v for k, v in entry.items() if k != "decision"}
            )
            merged[key] = old
        else:
            merged[key] = entry
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
    db: Session,
    assessment_id: int,
    decision: str,
    task_id: int | None = None,
    material_id: int | None = None,
) -> list[dict]:
    """记录人工整改决策（remediate/reject/done），返回最新整改清单。

    条目定位：审查整改项用 task_id；待更新项（stale，无审查任务）用 material_id。
    """
    assessment = db.get(ImpactAssessment, assessment_id)
    if assessment is None:
        raise KeyError("影响评估不存在")
    items = assessment.items or {}
    remediation = items.get("remediation") or []
    if task_id is not None:
        entry = next((e for e in remediation if e.get("task_id") == task_id), None)
        missing = f"整改项 task_id={task_id} 不存在"
    elif material_id is not None:
        entry = next((e for e in remediation if e.get("material_id") == material_id), None)
        missing = f"整改项 material_id={material_id} 不存在"
    else:
        raise KeyError("需提供 task_id 或 material_id 定位整改项")
    if entry is None:
        raise KeyError(missing)
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
