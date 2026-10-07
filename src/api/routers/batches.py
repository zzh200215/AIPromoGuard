"""审查批次管理：批量上传建任务、批次列表/详情、批量导出报告。"""

import io
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.middleware.auth import (
    batch_access_filter,
    ensure_batch_access,
    get_current_user,
    require_permission,
)
from src.api.schemas.batch import BatchOut
from src.api.schemas.task import TaskOut
from src.infrastructure.database.mysql import get_db
from src.models import ReviewBatch, ReviewResult, ReviewTask, User
from src.services.review_service import reset_failed_task_for_retry, start_review
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/batches", tags=["batches"])

ALLOWED_EXTS = {"pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "bmp"}
MAX_SIZE = 50 * 1024 * 1024  # 对齐单文件上限


@router.post("", status_code=201)
def create_batch(
    files: list[UploadFile] = File(...),
    batch_name: str = Form("批量审查"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("create_task")),
) -> dict:
    if not files or len(files) > 20:
        raise AppError(ErrorCode.PARAM_ERROR, "批次数目需在 1-20 份之间")

    # 先完整校验再落库，避免校验失败留下孤儿批次
    contents: list[tuple[UploadFile, str, str]] = []
    for f in files:
        filename = f.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTS:
            raise AppError(ErrorCode.FILE_TYPE_NOT_SUPPORTED, f"文件格式不支持: .{ext}")
        contents.append((f, filename, ext))

    batch = ReviewBatch(
        batch_name=batch_name, total_count=len(contents), created_by=current_user.id
    )
    db.add(batch)
    db.flush()

    task_ids: list[int] = []
    written_paths: list[Path] = []
    try:
        for upload, filename, ext in contents:
            doc_id = "doc_" + uuid.uuid4().hex[:8]
            dest_dir = Path(settings.upload_dir) / str(current_user.id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{doc_id}.{ext}"
            written_paths.append(dest)
            size = 0
            with dest.open("wb") as output:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_SIZE:
                        raise AppError(ErrorCode.FILE_TOO_LARGE)
                    output.write(chunk)
            task = ReviewTask(
                task_name=filename,
                document_name=filename,
                document_path=str(dest),
                status="pending",
                created_by=current_user.id,
                batch_id=batch.id,
            )
            db.add(task)
            db.flush()
            task_ids.append(task.id)
        db.commit()
    except Exception:
        db.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise

    for task_id in task_ids:
        start_review(task_id)
    return ok(
        {
            "batch_id": batch.id,
            "batch_name": batch.batch_name,
            "total_count": batch.total_count,
            "task_ids": task_ids,
        }
    )


@router.get("")
def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(ReviewBatch).order_by(ReviewBatch.created_at.desc())
    if current_user.role != "admin":
        query = query.join(User, User.id == ReviewBatch.created_by).filter(
            batch_access_filter(current_user)
        )
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [BatchOut.model_validate(b).model_dump() for b in items],
        }
    )


@router.get("/{batch_id}")
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    batch = db.get(ReviewBatch, batch_id)
    if batch is not None:
        ensure_batch_access(db, batch, current_user)
    if batch is None:
        raise AppError(ErrorCode.PARAM_ERROR, "批次不存在", http_status=404)
    tasks = (
        db.query(ReviewTask)
        .filter(ReviewTask.batch_id == batch_id)
        .order_by(ReviewTask.id.asc())
        .all()
    )
    return ok(
        {
            "batch": BatchOut.model_validate(batch).model_dump(),
            "tasks": [TaskOut.model_validate(t).model_dump() for t in tasks],
        }
    )


@router.post("/{batch_id}/retry-failed")
def retry_batch_failed(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("create_task")),
) -> dict:
    """一键重试批内全部失败任务；文档文件已被清理的任务跳过并计数返回。"""
    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise AppError(ErrorCode.PARAM_ERROR, "批次不存在", http_status=404)
    ensure_batch_access(db, batch, current_user)

    failed = (
        db.query(ReviewTask)
        .filter(ReviewTask.batch_id == batch_id, ReviewTask.status == "failed")
        .all()
    )
    retried: list[int] = []
    skipped = 0
    for task in failed:
        if not task.document_path or not Path(task.document_path).exists():
            skipped += 1
            continue
        reset_failed_task_for_retry(db, task)
        retried.append(task.id)
    db.commit()
    for task_id in retried:
        start_review(task_id)
    return ok({"batch_id": batch_id, "retried": retried, "skipped": skipped})


def _safe_zip_name(name: str | None, task_id: int) -> str:
    """把任务名压成安全的 zip 条目名：去路径分隔符、控制字符与 ..，空名回退 task_id。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").replace("..", "_").strip(" .")
    return cleaned[:120] or f"task_{task_id}"


@router.get("/{batch_id}/export")
def export_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
):
    """导出批内已完成任务的 Markdown 报告为 zip；有未完成任务时拒绝。"""
    batch = db.get(ReviewBatch, batch_id)
    if batch is not None:
        ensure_batch_access(db, batch, current_user)
    if batch is None:
        raise AppError(ErrorCode.PARAM_ERROR, "批次不存在", http_status=404)
    tasks = db.query(ReviewTask).filter(ReviewTask.batch_id == batch_id).all()
    pending = [t for t in tasks if t.status != "completed"]
    if pending:
        raise AppError(
            ErrorCode.TASK_INVALID_STATE,
            f"尚有 {len(pending)} 个任务未完成，无法导出",
        )
    if not tasks:
        raise AppError(ErrorCode.PARAM_ERROR, "批次为空", http_status=400)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in tasks:
            md = Path(t.report_path).with_suffix(".md") if t.report_path else None
            if md and md.exists():
                # task_name 默认取上传文件名：剔除路径分隔符与 .. 等成分，防 Zip Slip
                safe = _safe_zip_name(t.task_name, t.id)
                zf.writestr(f"{safe}.md", md.read_text(encoding="utf-8"))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(batch.batch_name)}.zip"
        },
    )


@router.get("/{batch_id}/export-summary")
def export_batch_summary(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
):
    """批次汇总表（xlsx）：逐任务违规统计，未完成任务也在列（状态标明）。

    公司场景的汇报/归档口径：一份表看清整批判定结果，不必逐个开报告。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise AppError(ErrorCode.PARAM_ERROR, "批次不存在", http_status=404)
    ensure_batch_access(db, batch, current_user)
    tasks = db.query(ReviewTask).filter(ReviewTask.batch_id == batch_id).all()
    if not tasks:
        raise AppError(ErrorCode.PARAM_ERROR, "批次为空", http_status=400)

    # 一次查询取整批结果，按任务聚合风险与人工判定
    task_ids = [t.id for t in tasks]
    rows = (
        db.query(
            ReviewResult.task_id,
            ReviewResult.risk_level,
            ReviewResult.status,
            func.count(ReviewResult.id),
        )
        .filter(ReviewResult.task_id.in_(task_ids))
        .group_by(ReviewResult.task_id, ReviewResult.risk_level, ReviewResult.status)
        .all()
    )
    agg: dict[int, dict[str, int]] = {
        tid: {"total": 0, "high": 0, "medium": 0, "low": 0, "confirmed": 0,
              "false_positive": 0, "pending_confirm": 0}
        for tid in task_ids
    }
    for tid, risk, status, count in rows:
        a = agg[tid]
        a["total"] += count
        if risk in ("high", "medium", "low"):
            a[risk] += count
        if status in ("confirmed", "false_positive", "pending_confirm"):
            a[status] += count

    STATUS_TEXT = {"completed": "已完成", "failed": "失败", "running": "进行中",
                   "pending": "排队中", "awaiting_review": "待人工复核", "cancelled": "已取消"}
    wb = Workbook()
    ws = wb.active
    ws.title = "批次汇总"
    headers = ["任务ID", "任务名", "文档", "领域", "状态", "违规总数",
               "高风险", "中风险", "低风险", "已确认", "误报", "待复核", "完成时间"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for t in tasks:
        a = agg[t.id]
        ws.append([
            t.id,
            t.task_name,
            t.document_name,
            t.domain or "",
            STATUS_TEXT.get(t.status, t.status),
            a["total"], a["high"], a["medium"], a["low"],
            a["confirmed"], a["false_positive"], a["pending_confirm"],
            t.completed_at.strftime("%Y-%m-%d %H:%M:%S") if t.completed_at else "",
        ])
    widths = [8, 30, 26, 10, 10, 9, 8, 8, 8, 8, 8, 8, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    filename = quote(f"批次汇总_{batch.batch_name}.xlsx")
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
