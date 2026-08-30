"""审查任务管理。"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.middleware.auth import (
    ensure_task_access,
    get_current_user,
    require_permission,
    task_access_filter,
)
from src.api.schemas.task import HumanReviewDecision, TaskCreate, TaskOut
from src.core.profiles import normalize_profile
from src.infrastructure.database.mysql import get_db
from src.models import ReviewTask, User
from src.services.review_service import resume_human_review, start_review
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("create_task")),
) -> dict:
    user_upload_dir = Path(settings.upload_dir) / str(current_user.id)
    matched = list(user_upload_dir.glob(f"{body.document_id}.*"))
    if not matched:
        raise AppError(ErrorCode.PARAM_ERROR, "文档不存在，请先上传", http_status=404)
    # schema 已白名单校验 document_id，此处再断言命中文件确实位于本人目录（纵深防御）
    if matched[0].parent.resolve() != user_upload_dir.resolve():
        raise AppError(ErrorCode.PARAM_ERROR, "非法的文档标识", http_status=400)
    document_name = matched[0].name
    base_name = None
    base_path = None
    if body.base_document_id:
        base_matched = list(user_upload_dir.glob(f"{body.base_document_id}.*"))
        if not base_matched:
            raise AppError(ErrorCode.PARAM_ERROR, "旧版文档不存在，请先上传", http_status=404)
        if base_matched[0].parent.resolve() != user_upload_dir.resolve():
            raise AppError(ErrorCode.PARAM_ERROR, "非法的文档标识", http_status=400)
        base_name = base_matched[0].name
        base_path = str(base_matched[0])
    try:
        profile = normalize_profile(body.profile)
    except ValueError as exc:
        raise AppError(ErrorCode.PARAM_ERROR, str(exc)) from exc
    task = ReviewTask(
        task_name=body.task_name or document_name,
        document_name=document_name,
        document_path=str(matched[0]),
        document_type=body.document_type,
        domain=body.domain,
        profile=profile,
        status="pending",
        created_by=current_user.id,
        base_document_name=base_name,
        base_document_path=base_path,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    start_review(task.id)
    return ok(
        {
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at.isoformat(),
        }
    )


@router.get("")
def list_tasks(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(ReviewTask)
    if current_user.role != "admin":
        query = query.join(User, User.id == ReviewTask.created_by).filter(
            task_access_filter(current_user)
        )
    if status:
        query = query.filter(ReviewTask.status == status)
    total = query.count()
    items = (
        query.order_by(ReviewTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [TaskOut.model_validate(t).model_dump() for t in items],
        }
    )


@router.get("/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok(TaskOut.model_validate(task).model_dump())


@router.post("/{task_id}/human-review")
def submit_human_review(
    task_id: int,
    body: HumanReviewDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("confirm")),
) -> dict:
    """提交人工复核决策，从 checkpoint 续跑剩余审查图（LangGraph interrupt 恢复）。

    仅 workflow.human_review.enabled=true 时任务会进入 awaiting_review 状态；
    待复核清单见任务详情 stages.human_review.pending。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    summary = resume_human_review(task_id, body.rejected_indexes)
    return ok(summary)
