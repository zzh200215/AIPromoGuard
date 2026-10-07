"""规则库管理（CRUD）。规则引擎执行在 W3 接入。"""


from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user, require_permission
from src.api.schemas.rule import RuleCreate, RuleOut, RuleUpdate
from src.infrastructure.database.mysql import get_db
from src.models import ReviewBatch, ReviewResult, ReviewTask, Rule, User
from src.services.review_service import start_review
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("")
def list_rules(
    domain: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(Rule)
    if domain:
        query = query.filter(Rule.domain == domain)
    if is_active is not None:
        query = query.filter(Rule.is_active == (1 if is_active else 0))
    total = query.count()
    items = (
        query.order_by(Rule.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [RuleOut.model_validate(r).model_dump() for r in items],
        }
    )


@router.post("", status_code=201)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    """新建规则一律落草稿（is_active=0），须经 /publish 发布后才参与审查扫描。"""
    rule = Rule(**body.model_dump(), is_active=0, status="draft")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return ok(RuleOut.model_validate(rule).model_dump())


@router.get("/{rule_id}")
def get_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)
    return ok(RuleOut.model_validate(rule).model_dump())


@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)
    updates = body.model_dump(exclude_unset=True)
    if "is_active" in updates:
        updates["is_active"] = 1 if updates.pop("is_active") else 0
    for field, value in updates.items():
        setattr(rule, field, value)
    # 门禁：仅生效中（status=active）的规则允许启停开关，草稿/待复核不能绕过发布直接激活
    if rule.status != "active":
        rule.is_active = 0
    rule.version += 1
    db.commit()
    db.refresh(rule)
    return ok(RuleOut.model_validate(rule).model_dump())


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)
    # 无外键约束，应用层防孤儿数据：被审查结果引用的规则只能停用不能删
    referenced = db.query(ReviewResult).filter(ReviewResult.rule_id == rule_id).count()
    if referenced:
        raise AppError(
            ErrorCode.PARAM_ERROR,
            f"该规则已被 {referenced} 条审查结果引用，不能删除；可将规则停用（is_active=false）",
            http_status=409,
        )
    db.delete(rule)
    db.commit()
    return ok({"deleted": rule_id})


@router.post("/{rule_id}/versions", status_code=201)
def draft_new_version(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    """从现行规则起草新版本：克隆为 draft（不生效），编辑后走 publish 发布。"""
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)
    draft = Rule(
        domain=rule.domain,
        rule_name=rule.rule_name,
        rule_type=rule.rule_type,
        rule_content=dict(rule.rule_content or {}),
        severity=rule.severity,
        description=rule.description,
        is_active=0,
        version=rule.version + 1,
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return ok(RuleOut.model_validate(draft).model_dump())


@router.post("/{rule_id}/publish")
def publish_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    """发布规则版本：草稿/待复核版本激活生效，同名旧版本自动停用。"""
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)
    if rule.status not in ("draft", "pending_review"):
        raise AppError(
            ErrorCode.PARAM_ERROR, f"规则当前状态 {rule.status}，仅草稿/待复核可发布"
        )
    rule.status = "active"
    rule.is_active = 1
    superseded = (
        db.query(Rule)
        .filter(
            Rule.rule_name == rule.rule_name,
            Rule.id != rule.id,
            Rule.status == "active",
            Rule.is_active == 1,
        )
        .all()
    )
    for old in superseded:
        old.is_active = 0
    db.commit()
    db.refresh(rule)
    return ok(
        {
            "rule": RuleOut.model_validate(rule).model_dump(),
            "superseded_rule_ids": [old.id for old in superseded],
        }
    )


@router.post("/{rule_id}/re-review")
def rereview_rule_tasks(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_rules")),
) -> dict:
    """规则重审：用当前生效规则集重跑历史上命中过该规则的任务。

    规则发布/精调只影响之后的任务；本接口补上"变更后应重看历史材料"的口子——
    按 review_results.rule_id 圈定历史任务，原文档仍在盘上的创建重审批次逐个入队。
    """
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)

    history_ids = [
        row[0]
        for row in db.query(ReviewResult.task_id)
        .filter(ReviewResult.rule_id == rule_id)
        .distinct()
        .all()
    ]
    if not history_ids:
        raise AppError(ErrorCode.PARAM_ERROR, "没有历史任务命中过该规则，无需重审")

    hist_tasks = db.query(ReviewTask).filter(ReviewTask.id.in_(history_ids)).all()
    skipped: list[dict] = []
    resolved: list[ReviewTask] = []
    seen_paths: set[str] = set()
    for t in hist_tasks:
        if not t.document_path or not Path(t.document_path).exists():
            skipped.append({"task_id": t.id, "name": t.task_name, "reason": "原文档已不存在"})
            continue
        # 同一文档被多个历史任务审过时只重跑一次
        if t.document_path in seen_paths:
            continue
        seen_paths.add(t.document_path)
        resolved.append(t)
    if not resolved:
        raise AppError(
            ErrorCode.PARAM_ERROR, f"历史任务的原文档均已缺失（{len(skipped)} 个被跳过），无法重审"
        )

    batch = ReviewBatch(
        batch_name=f"规则重审：{rule.rule_name}"[:255],
        total_count=len(resolved),
        created_by=current_user.id,
        source_type="rule_re_review",
        source_id=rule.id,
    )
    db.add(batch)
    db.flush()
    task_ids = []
    for t in resolved:
        task = ReviewTask(
            task_name=f"[重审]{t.task_name}"[:255],
            document_name=t.document_name,
            document_path=t.document_path,
            document_type=t.document_type,
            domain=t.domain,
            profile=t.profile,
            status="pending",
            created_by=current_user.id,
            batch_id=batch.id,
        )
        db.add(task)
        db.flush()
        task_ids.append(task.id)
    db.commit()

    for task_id in task_ids:
        start_review(task_id)
    return ok(
        {
            "batch_id": batch.id,
            "batch_name": batch.batch_name,
            "total_count": batch.total_count,
            "task_ids": task_ids,
            "skipped": skipped,
        }
    )
