"""规则库管理（CRUD）。规则引擎执行在 W3 接入。"""


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user, require_permission
from src.api.schemas.rule import RuleCreate, RuleOut, RuleUpdate
from src.infrastructure.database.mysql import get_db
from src.models import ReviewResult, Rule, User
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
    data = body.model_dump()
    data["is_active"] = 1 if data.pop("is_active") else 0
    rule = Rule(**data)
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
