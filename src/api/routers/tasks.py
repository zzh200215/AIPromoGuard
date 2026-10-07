"""审查任务管理。"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.api.middleware.auth import (
    ensure_task_access,
    get_current_user,
    require_permission,
    task_access_filter,
)
from src.api.schemas.task import HumanReviewDecision, SignOffRequest, TaskCreate, TaskOut
from src.core.profiles import normalize_profile
from src.infrastructure.database.mysql import get_db
from src.models import AuditLog, ReviewResult, ReviewTask, TaskSignOff, User
from src.services.document_service import document_service
from src.services.review_service import (
    reset_failed_task_for_retry,
    resume_human_review,
    start_review,
)
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/tasks", tags=["tasks"])

# F2-2 原图预览的媒体类型映射（与 ALLOWED_EXTS 的可视子集对齐）
MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "bmp": "image/bmp",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
}


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
    search: str | None = Query(None, max_length=100, description="任务名/文档名关键词"),
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
    if search:
        keyword = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ReviewTask.task_name.like(keyword),
                ReviewTask.document_name.like(keyword),
            )
        )
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


@router.get("/{task_id}/document-content")
def get_task_document_content(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """任务文档解析原文（带页/段位置），供人工复核的原文对照视图。

    按需解析不落库：OCR 等慢解析只发生在复核人打开对照视图时；
    返回文本与审查管线同样经过脱敏（document_service.parse）。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if not task.document_path or not Path(task.document_path).exists():
        raise AppError(ErrorCode.PARAM_ERROR, "任务文档文件已不存在", http_status=404)
    try:
        parsed = document_service.parse(task.document_path)
    except AppError:
        raise
    except Exception as exc:  # 解析器内部异常统一转参数错误语义，避免 500 裸栈
        raise AppError(ErrorCode.PARAM_ERROR, f"文档解析失败: {exc}") from exc
    return ok(
        {
            "task_id": task_id,
            "document_name": task.document_name,
            "blocks": [
                {
                    "text": block.text,
                    "page": block.page,
                    "paragraph": block.paragraph,
                    "heading": block.heading,
                }
                for block in parsed.blocks
            ],
        }
    )


@router.get("/{task_id}/document-file")
def get_task_document_file(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """任务原始文件流（F2-2）：图片类材料的视觉层复核需要看到原图。

    鉴权与 document-content 同源（任务访问控制）——不加目录浏览，
    只服务已入库任务的文件。前端经 axios 带 token 取 blob 再转 objectURL，
    避免 <img src> 无法携带认证头的问题。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if not task.document_path or not Path(task.document_path).exists():
        raise AppError(ErrorCode.PARAM_ERROR, "任务文档文件已不存在", http_status=404)
    path = Path(task.document_path)
    media = MEDIA_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return FileResponse(path=path, media_type=media, filename=task.document_name or path.name)


@router.post("/{task_id}/retry")
def retry_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("create_task")),
) -> dict:
    """重试失败任务：复位任务状态与批次计数后重新入队。

    仅 failed 终态可重试；结果落库先删后插，重跑幂等，不产生重复结论。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if task.status != "failed":
        raise AppError(ErrorCode.TASK_INVALID_STATE, "只有失败的任务可以重试")
    if not task.document_path or not Path(task.document_path).exists():
        raise AppError(ErrorCode.PARAM_ERROR, "任务文档文件已不存在，无法重试", http_status=404)
    reset_failed_task_for_retry(db, task)
    db.commit()
    start_review(task.id)
    return ok({"task_id": task.id, "status": task.status})


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


@router.post("/{task_id}/sign-off")
def sign_off_task(
    task_id: int,
    body: SignOffRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("confirm")),
) -> dict:
    """审核签发：报告定稿后的正式放行/驳回动作（合规闭环收口）。

    门槛：任务已完成且待复核清零——带未处理复核项的报告不允许签发。
    多次签发留痕，最新一次为有效结论；签发人/结论/意见写审计日志。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if task.status != "completed":
        raise AppError(ErrorCode.TASK_INVALID_STATE, "任务完成后才能签发")
    pending = (
        db.query(func.count(ReviewResult.id))
        .filter(ReviewResult.task_id == task.id, ReviewResult.status == "pending_confirm")
        .scalar()
    )
    if pending:
        raise AppError(
            ErrorCode.TASK_INVALID_STATE,
            f"还有 {pending} 条待复核未处理，签发前需完成人工判定",
        )
    record = TaskSignOff(
        task_id=task.id,
        user_id=current_user.id,
        username=current_user.username,
        decision=body.decision,
        note=body.note,
    )
    db.add(record)
    db.add(
        AuditLog(
            user_id=current_user.id,
            username=current_user.username,
            action="task.sign_off",
            resource_type="review_task",
            resource_id=str(task.id),
            detail=json.dumps(
                {"decision": body.decision, "note": body.note}, ensure_ascii=False
            ),
        )
    )
    db.commit()
    db.refresh(record)
    return ok(
        {
            "task_id": task.id,
            "decision": record.decision,
            "username": record.username,
            "note": record.note,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
    )


@router.get("/{task_id}/sign-off")
def get_sign_off(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """查询任务当前有效签发结论（最新一次），无则返回 None。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    record = (
        db.query(TaskSignOff)
        .filter(TaskSignOff.task_id == task.id)
        .order_by(TaskSignOff.id.desc())
        .first()
    )
    return ok(
        {
            "task_id": task.id,
            "decision": record.decision if record else None,
            "username": record.username if record else None,
            "note": record.note if record else None,
            "created_at": record.created_at.isoformat()
            if record and record.created_at
            else None,
        }
    )
