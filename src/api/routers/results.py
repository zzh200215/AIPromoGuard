"""审查结果管理：按任务列出结果、人工确认违规/误报、反馈闭环统计（PRD §5.5 / §3.2.4）。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.middleware.auth import ensure_task_access, require_permission
from src.api.schemas.rule import RuleOut
from src.infrastructure.database.mysql import get_db
from src.models import Article, AuditLog, Regulation, ReviewResult, ReviewTask, Rule, User
from src.services.rule_tuning import apply_suggestion, build_rule_suggestions
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(tags=["results"])

_STATUSES = {"pending_confirm", "confirmed", "false_positive"}


@router.get("/tasks/{task_id}/results")
def list_results(
    task_id: int,
    status: str | None = None,
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
    items = query.order_by(ReviewResult.id.asc()).all()

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

    return ok(
        {
            "task_id": task_id,
            "total": len(items),
            "items": [
                {
                    "result_id": r.id,
                    "violation_type": r.violation_type,
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
                    "auto_confirmed": r.confirmed_by == 0,  # 系统自动确认（方向②分流）
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
    before_auto_confirmed = result.confirmed_by == 0
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
    return ok(
        {
            "result_id": result.id,
            "status": result.status,
            "confirmed_by": result.confirmed_by,
            "confirmed_at": result.confirmed_at.isoformat(),
            "auto_confirmed": result.confirmed_by == 0,
        }
    )


@router.get("/results/feedback-stats")
def feedback_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """反馈闭环统计（W17）：按检出来源（规则/LLM/混合）聚合人工确认结果。

    仅统计人工复核过的结果（confirmed_by>0）：方向②的自动确认（confirmed_by=0）
    不计入，保证确认率/误报率反映真实人工判定，避免自动分流污染精调数据。
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

    仅统计已人工复核的结果（confirmed_by>0，confirmed + false_positive），
    按误报率降序。方向②自动确认（confirmed_by=0）不计入，避免虚高确认率。
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
