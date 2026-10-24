"""审查结果管理：按任务列出结果、人工确认违规/误报、反馈闭环统计（PRD §5.5 / §3.2.4）。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.api.middleware.auth import ensure_task_access, require_permission
from src.api.schemas.rule import RuleOut
from src.infrastructure.database.mysql import get_db
from src.models import Article, AuditLog, Regulation, ReviewResult, ReviewTask, Rule, User
from src.services.precedent_memory import sync_after_verdict
from src.services.result_trail import build_trail
from src.services.rule_tuning import apply_suggestion, build_rule_suggestions
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(tags=["results"])

_STATUSES = {"pending_confirm", "confirmed", "false_positive"}


@router.get("/tasks/{task_id}/results")
def list_results(
    task_id: int,
    status: str | None = None,
    order: str = Query("id", pattern="^(id|priority)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    query = db.query(ReviewResult).filter(ReviewResult.task_id == task_id)
    if status:
        query = query.filter(ReviewResult.status == status)
    if order == "priority":
        # R4-3 低置信优先复核路由：排序键 = (1 - 置信度) × 风险权重 降序。
        # 业界共识"人工只看最难案例"：低置信 = 系统最拿不准（AI 判断力的
        # 边界），高风险 = 危害最大——复核人从"最可疑且最危险"的看起。
        weight = case(
            (ReviewResult.risk_level == "high", 3),
            (ReviewResult.risk_level == "medium", 2),
            else_=1,
        )
        query = query.order_by(
            ((1 - ReviewResult.confidence_score) * weight).desc()
        )
    else:
        query = query.order_by(ReviewResult.id.asc())
    items = query.all()

    # 法规溯源展示：regulation/article 表都不大，直接建查找字典（无关联时字段为 None）
    reg_ids = {r.regulation_id for r in items if r.regulation_id}
    art_ids = {r.article_id for r in items if r.article_id}
    reg_meta = (
        {
            x.id: x
            for x in db.query(Regulation)
            .filter(Regulation.id.in_(reg_ids))
            .all()
        }
        if reg_ids
        else {}
    )
    articles = (
        {x.id: x for x in db.query(Article).filter(Article.id.in_(art_ids)).all()}
        if art_ids
        else {}
    )

    def _reg_field(r: ReviewResult, attr: str) -> str | None:
        regulation = reg_meta.get(r.regulation_id) if r.regulation_id else None
        value = getattr(regulation, attr) if regulation else None
        return value.isoformat() if value else None

    def _basis(r: ReviewResult) -> dict:
        regulation = reg_meta.get(r.regulation_id) if r.regulation_id else None
        article = articles.get(r.article_id) if r.article_id else None
        return {
            "regulation_id": r.regulation_id,
            "article_id": r.article_id,
            "regulation_name": regulation.regulation_name if regulation else None,
            "regulation_no": regulation.regulation_no if regulation else None,
            "publish_date": _reg_field(r, "publish_date"),
            "effective_date": _reg_field(r, "effective_date"),
            "article_no": article.article_no if article else None,
            "article_excerpt": article.content[:80] if article else None,
        }

    # 内置维度身份（F1-2）：review_service 落库时把 rule_name 并入 description 头部
    # （"[敏感信息：手机号] …"），此处据此派生 finding_kind 供前端渲染专属标签。
    # 前缀常量从检测器单点 import——文案改动会被测试拦截，不会静默失效。
    from src.core.rule_engine.consistency import CONSISTENCY_KIND_PREFIX
    from src.core.rule_engine.pii_scan import PII_KIND_PREFIX
    from src.services.tamper_check import TAMPER_KIND_PREFIX

    _KIND_PREFIXES = (
        (PII_KIND_PREFIX, "pii"),
        (CONSISTENCY_KIND_PREFIX, "consistency"),
        (TAMPER_KIND_PREFIX, "tamper"),
    )

    def _finding_kind(r: ReviewResult) -> str | None:
        desc = r.description or ""
        for prefix, kind in _KIND_PREFIXES:
            if desc.startswith(f"[{prefix}"):
                return kind
        return "visual" if r.violation_type == "vlm" else None

    return ok(
        {
            "task_id": task_id,
            "total": len(items),
            "items": [
                {
                    "result_id": r.id,
                    "violation_type": r.violation_type,
                    "finding_kind": _finding_kind(r),
                    "risk_level": r.risk_level,
                    "original_text": r.original_text,
                    "location_page": r.location_page,
                    "location_paragraph": r.location_paragraph,
                    "rule_id": r.rule_id,
                    "confidence_score": float(r.confidence_score),
                    "description": r.description,
                    "suggestion": r.suggestion,
                    "status": r.status,
                    "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                    "confirmed_by": r.confirmed_by,
                    "auto_confirmed": r.auto_confirmed,  # 系统自动确认（方向②分流）
                    **_basis(r),
                }
                for r in items
            ],
        }
    )


class ConfirmRequest(BaseModel):
    verdict: str = Field(
        ...,
        description="confirmed | false_positive",
        pattern="^(confirmed|false_positive)$",
    )
    note: str | None = None

class BulkConfirmRequest(BaseModel):
    result_ids: list[int] = Field(..., min_length=1, max_length=200)
    verdict: str = Field(
        ...,
        description="confirmed | false_positive",
        pattern="^(confirmed|false_positive)$",
    )
    note: str | None = None


@router.get("/results/{result_id}/trail")
def result_trail(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """结论生命周期时间线（F2-3）：检出 → 系统分流 → 人工判定/翻案 → 撤销。

    数据源全是既有留痕（ReviewResult + AuditLog），供工作台详情面板回放
    判定轨迹——审计员四问中"能否事后追溯"的页面侧答案（导出侧见证据包）。
    """
    result = db.get(ReviewResult, result_id)
    if result is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    task = db.get(ReviewTask, result.task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)

    ops = (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_type == "review_result",
            AuditLog.resource_id == str(result_id),
        )
        .order_by(AuditLog.id)
        .all()
    )
    return ok(
        {
            "result_id": result_id,
            "task_id": result.task_id,
            "events": build_trail(result, ops),
        }
    )


@router.post("/results/{result_id}/confirm")
def confirm_result(
    result_id: int,
    body: ConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("confirm")),
) -> dict:
    """人工判定/翻案（方向②）：任何状态均可提交 verdict。

    - pending_confirm → confirmed/false_positive（常规复核）；
    - confirmed ↔ false_positive（翻案，用于纠正系统自动确认或误判）。
    翻案后 confirmed_by 覆盖为当前用户（进入人工复核统计），confirmed_at 刷新。
    """
    result = db.get(ReviewResult, result_id)
    if result is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    task = db.get(ReviewTask, result.task_id)
    if task is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    # 判定前留痕：翻案率（采纳率报告口径）依赖"翻转前状态 + 是否系统自动确认"，
    # confirmed_by 翻案后会被覆盖，事后无从还原，必须在这里落审计。
    before_status = result.status
    before_auto_confirmed = result.auto_confirmed
    result.status = body.verdict
    result.confirmed_at = datetime.now()
    result.confirmed_by = current_user.id
    if body.note:
        result.description = (result.description or "") + f"\n[复核] {body.note}"
    db.add(
        AuditLog(
            user_id=current_user.id,
            username=current_user.username,
            action="result.confirm",
            resource_type="review_result",
            resource_id=str(result.id),
            detail=json.dumps(
                {
                    # task_id 用于结论删除（任务重跑清空旧结论）后仍可归属回任务
                    "task_id": result.task_id,
                    "before_status": before_status,
                    "before_auto_confirmed": before_auto_confirmed,
                    "verdict": body.verdict,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    db.refresh(result)
    # 判定先例记忆（第 2 批）：人工终态结论沉淀为可召回先例（失败不阻塞判定）
    sync_after_verdict(db, result)
    return ok(
        {
            "result_id": result.id,
            "status": result.status,
            "confirmed_by": result.confirmed_by,
            "confirmed_at": result.confirmed_at.isoformat(),
            "auto_confirmed": result.auto_confirmed,
        }
    )


@router.post("/results/bulk-confirm")
def bulk_confirm_results(
    body: BulkConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("confirm")),
) -> dict:
    """批量人工判定（确认 / 剔除误报）。

    逐条复用单条确认的鉴权与留痕逻辑：无权访问的任务条目跳过并在
    skipped 中说明原因，不作整体失败；每条判定各落一条审计（含 bulk 标记）。
    """
    unique_ids = list(dict.fromkeys(body.result_ids))
    skipped: list[dict] = []
    touched: list[ReviewResult] = []  # 判定成功条目（提交后沉淀先例用）
    updated = 0
    now = datetime.now()
    for rid in unique_ids:
        result = db.get(ReviewResult, rid)
        if result is None:
            skipped.append({"result_id": rid, "reason": "not_found"})
            continue
        task = db.get(ReviewTask, result.task_id)
        if task is None:
            skipped.append({"result_id": rid, "reason": "task_missing"})
            continue
        try:
            ensure_task_access(db, task, current_user)
        except AppError:
            skipped.append({"result_id": rid, "reason": "forbidden"})
            continue
        before_status = result.status
        before_auto_confirmed = result.auto_confirmed
        result.status = body.verdict
        result.confirmed_at = now
        result.confirmed_by = current_user.id
        if body.note:
            result.description = (result.description or "") + f"\n[批量复核] {body.note}"
        db.add(
            AuditLog(
                user_id=current_user.id,
                username=current_user.username,
                action="result.confirm",
                resource_type="review_result",
                resource_id=str(result.id),
                detail=json.dumps(
                    {
                        # task_id：结论删除后仍可归属回任务（见单条 confirm 同字段说明）
                        "task_id": result.task_id,
                        "before_status": before_status,
                        "before_auto_confirmed": before_auto_confirmed,
                        "verdict": body.verdict,
                        "bulk": True,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        updated += 1
        touched.append(result)
    db.commit()
    # 批量判定同样沉淀先例（sync_after_verdict 内部自带失败降级）
    for result in touched:
        sync_after_verdict(db, result)
    return ok({"updated": updated, "skipped": skipped})


class RevertRequest(BaseModel):
    """撤销人工判定的入参：恢复为待复核，用于误操作回退。"""

    result_ids: list[int] = Field(..., min_length=1, max_length=200)
    note: str | None = None


@router.post("/results/revert")
def revert_results(
    body: RevertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("confirm")),
) -> dict:
    """撤销人工判定：confirmed / false_positive 恢复为 pending_confirm。

    供前端批量判定后的「撤销」使用：把每条恢复到操作前状态。已是待复核的
    条目幂等跳过（already_pending）；confirmed_by/confirmed_at 一并清空，
    翻案率等统计口径依赖审计日志的 before_status，不受撤销覆盖影响。
    """
    unique_ids = list(dict.fromkeys(body.result_ids))
    skipped: list[dict] = []
    reverted: list[ReviewResult] = []  # 撤销成功条目（提交后清理先例用）
    updated = 0
    for rid in unique_ids:
        result = db.get(ReviewResult, rid)
        if result is None:
            skipped.append({"result_id": rid, "reason": "not_found"})
            continue
        task = db.get(ReviewTask, result.task_id)
        if task is None:
            skipped.append({"result_id": rid, "reason": "task_missing"})
            continue
        try:
            ensure_task_access(db, task, current_user)
        except AppError:
            skipped.append({"result_id": rid, "reason": "forbidden"})
            continue
        if result.status == "pending_confirm":
            skipped.append({"result_id": rid, "reason": "already_pending"})
            continue
        before_status = result.status
        result.status = "pending_confirm"
        result.confirmed_at = None
        result.confirmed_by = None
        if body.note:
            result.description = (result.description or "") + f"\n[撤销复核] {body.note}"
        db.add(
            AuditLog(
                user_id=current_user.id,
                username=current_user.username,
                action="result.revert",
                resource_type="review_result",
                resource_id=str(result.id),
                detail=json.dumps(
                    {
                        # task_id：结论删除后仍可归属回任务（见单条 confirm 同字段说明）
                        "task_id": result.task_id,
                        "before_status": before_status,
                        "bulk": True,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        updated += 1
        reverted.append(result)
    db.commit()
    # 撤销复核 = 回到待定状态，先例随之删除（记忆始终等于最新人工判断）
    for result in reverted:
        sync_after_verdict(db, result)
    return ok({"updated": updated, "skipped": skipped})


@router.get("/results/feedback-stats")
def feedback_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """反馈闭环统计（W17）：按检出来源（规则/LLM/混合）聚合人工确认结果。

    仅统计人工复核过的结果（confirmed_by 指向真实用户）：方向②的自动确认
    （confirmed_by 为空，见 ReviewResult.auto_confirmed）不计入，保证确认率/误报率
    反映真实人工判定，避免自动分流污染精调数据。
    前端反馈统计页标记 adminOnly，此处后端同口径兜底（非 admin 仅可看自己
    任务的结果明细，不应看到全局精调统计）。
    """
    if current_user.role != "admin":
        raise AppError(ErrorCode.FORBIDDEN, http_status=403)
    rows = (
        db.query(ReviewResult.violation_type, ReviewResult.status, func.count(ReviewResult.id))
        .filter(ReviewResult.confirmed_by.isnot(None), ReviewResult.confirmed_by > 0)
        .group_by(ReviewResult.violation_type, ReviewResult.status)
        .all()
    )
    by_source: dict[str, dict[str, int]] = {}
    for vtype, status, count in rows:
        bucket = by_source.setdefault(vtype, {s: 0 for s in _STATUSES})
        bucket[status] = count

    def _rates(bucket: dict) -> dict:
        reviewed = bucket.get("confirmed", 0) + bucket.get("false_positive", 0)
        return {
            "confirmed": bucket.get("confirmed", 0),
            "false_positive": bucket.get("false_positive", 0),
            "pending_confirm": bucket.get("pending_confirm", 0),
            "confirm_rate": round(bucket.get("confirmed", 0) / reviewed, 3) if reviewed else None,
            "false_positive_rate": round(bucket.get("false_positive", 0) / reviewed, 3)
            if reviewed
            else None,
        }

    source_stats = {vtype: _rates(bucket) for vtype, bucket in by_source.items()}
    totals = {
        s: sum(bucket.get(s, 0) for bucket in by_source.values()) for s in _STATUSES
    }
    return ok(
        {
            "by_source": source_stats,
            "totals": totals,
            "overall_false_positive_rate": _rates(totals)["false_positive_rate"],
        }
    )


@router.get("/results/rules/quality")
def rules_quality(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """规则质量报告（W17）：按 rule_id 统计命中/确认/误报，锁定高误报规则供精调。

    仅统计已人工复核的结果（confirmed_by 指向真实用户，confirmed + false_positive），
    按误报率降序。方向②自动确认（无人工 actor）不计入，避免虚高确认率。
    """
    rows = (
        db.query(ReviewResult.rule_id, ReviewResult.status, func.count(ReviewResult.id))
        .filter(
            ReviewResult.rule_id.isnot(None),
            ReviewResult.confirmed_by.isnot(None),
            ReviewResult.confirmed_by > 0,
        )
        .group_by(ReviewResult.rule_id, ReviewResult.status)
        .all()
    )
    rule_names = {r.id: r.rule_name for r in db.query(Rule.id, Rule.rule_name).all()}

    acc: dict[int, dict[str, int]] = {}
    for rule_id, status, count in rows:
        bucket = acc.setdefault(rule_id, {s: 0 for s in _STATUSES})
        bucket[status] = count

    items = []
    for rule_id, bucket in acc.items():
        reviewed = bucket.get("confirmed", 0) + bucket.get("false_positive", 0)
        if reviewed == 0:
            continue
        fp_rate = bucket.get("false_positive", 0) / reviewed
        items.append(
            {
                "rule_id": rule_id,
                "rule_name": rule_names.get(rule_id),
                "hits": bucket.get("pending_confirm", 0) + reviewed,
                "confirmed": bucket.get("confirmed", 0),
                "false_positive": bucket.get("false_positive", 0),
                "pending_confirm": bucket.get("pending_confirm", 0),
                "confirm_rate": round(bucket.get("confirmed", 0) / reviewed, 3),
                "false_positive_rate": round(fp_rate, 3),
            }
        )
    items.sort(key=lambda x: x["false_positive_rate"], reverse=True)
    return ok({"total": len(items), "items": items})


@router.get("/results/rules/suggestions")
def rule_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """规则精调建议（方向③）：基于人工复核统计，对高误报规则给出可执行建议。

    建议实时计算不落库：deactivate（纯误报停用）/ remove_keyword（移除误报关键词），
    每条附误报样本供管理员判断，经 apply-suggestion 应用。
    """
    items = build_rule_suggestions(db)
    return ok({"total": len(items), "items": items})


class ApplySuggestionRequest(BaseModel):
    action: str = Field(..., pattern="^(deactivate|remove_keyword|set_threshold)$")
    condition_index: int | None = None
    keyword: str | None = None
    threshold: float | None = None


@router.post("/results/rules/{rule_id}/apply-suggestion")
def apply_rule_suggestion(
    rule_id: int,
    body: ApplySuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    """应用规则精调建议：deactivate 停用 / remove_keyword 移除关键词 / set_threshold
    抬本规则阈值（version+1）。"""
    rule = apply_suggestion(
        db,
        rule_id,
        body.action,
        condition_index=body.condition_index,
        keyword=body.keyword,
        threshold=body.threshold,
    )
    return ok(RuleOut.model_validate(rule).model_dump())
