"""审查报告查询与下载。任务完成后从落盘文件读取真实报告。"""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from src.api.middleware.auth import ensure_task_access, get_current_user, require_permission
from src.core.report.docx import render_docx
from src.core.report.pdf import render_pdf
from src.infrastructure.database.mysql import get_db
from src.models import ReviewTask, User
from src.services.evidence_pack import build_evidence_zip, collect_evidence
from src.services.report_service import refresh_report
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger
from src.utils.response import ok

router = APIRouter(tags=["reports"])

logger = get_logger(__name__)

_FORMATS = {"markdown", "pdf", "docx"}


def _disposition(filename: str) -> str:
    """RFC 5987 编码中文文件名（HTTP 头仅允许 latin-1）。"""
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@router.get("/tasks/{task_id}/report")
def get_report(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)

    if task.status != "completed" or not task.report_path:
        return ok(
            {
                "task_id": task.id,
                "status": task.status,
                "progress": task.progress,
                "summary": {"total_violations": 0, "high_risk": 0, "medium_risk": 0, "low_risk": 0},
                "violations": [],
                "message": "报告生成中，请稍后重试",
            }
        )

    path = Path(task.report_path)
    if not path.exists():
        raise AppError(ErrorCode.INTERNAL_ERROR, "报告文件缺失", http_status=500)
    # 读取时同步人工结论：确认/翻案后报告过期则重算回写（合规留档口径）
    report_data = refresh_report(db, task)
    return ok(report_data)


@router.get("/tasks/{task_id}/report/download")
def download_report(
    task_id: int,
    format: str = "markdown",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
):
    """下载审查报告，支持 format=markdown|pdf|docx。"""
    if format not in _FORMATS:
        raise AppError(ErrorCode.PARAM_ERROR, f"不支持的格式: {format}（可选 markdown|pdf|docx）")

    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if task.status != "completed" or not task.report_path:
        raise AppError(ErrorCode.TASK_INVALID_STATE, "报告尚未生成")

    base = Path(task.report_path)
    if not base.exists():
        raise AppError(ErrorCode.INTERNAL_ERROR, "报告文件缺失", http_status=500)
    # 按最新人工结论渲染，避免导出文件与最终结论不一致
    report_data = refresh_report(db, task)

    if format == "pdf":
        try:
            content = bytes(render_pdf(report_data))  # fpdf2 返回 bytearray，需转 bytes
        except RuntimeError as exc:
            # 异常文本可能含字体搜索路径等内部细节，仅记日志不外透
            logger.exception("报告 PDF 渲染失败: task_id=%s", task_id)
            raise AppError(
                ErrorCode.INTERNAL_ERROR, "报告 PDF 生成失败，请联系管理员", http_status=500
            ) from exc
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": _disposition(f"审查报告_任务{task_id}.pdf")},
        )

    if format == "docx":
        try:
            content = render_docx(report_data)
        except Exception as exc:
            logger.exception("报告 DOCX 渲染失败: task_id=%s", task_id)
            raise AppError(
                ErrorCode.INTERNAL_ERROR, "报告 Word 生成失败，请联系管理员", http_status=500
            ) from exc
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": _disposition(f"审查报告_任务{task_id}.docx")},
        )

    md_path = base.with_suffix(".md")
    if not md_path.exists():
        raise AppError(ErrorCode.INTERNAL_ERROR, "报告文件缺失", http_status=500)
    return FileResponse(
        path=md_path,
        media_type="text/markdown; charset=utf-8",
        filename=f"审查报告_任务{task_id}.md",
    )


@router.get("/tasks/{task_id}/evidence-pack")
def download_evidence_pack(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
):
    """监管取证证据包（R1-2）：报告 + 结论生命周期 + 操作留痕，zip 内含 SHA256 manifest。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    if task.status != "completed" or not task.report_path:
        raise AppError(ErrorCode.TASK_INVALID_STATE, "报告尚未生成，无法导出证据包")

    base = Path(task.report_path)
    if not base.exists():
        raise AppError(ErrorCode.INTERNAL_ERROR, "报告文件缺失", http_status=500)
    # 与 download 口径一致：按最新人工结论刷新，保证"包内内容 == 数据库留痕"
    refresh_report(db, task)

    report, report_md, report_json, operations, meta = collect_evidence(db, task)
    try:
        content = build_evidence_zip(report, report_md, report_json, operations, meta)
    except Exception as exc:
        logger.exception("证据包生成失败: task_id=%s", task_id)
        raise AppError(
            ErrorCode.INTERNAL_ERROR, "证据包生成失败，请联系管理员", http_status=500
        ) from exc

    logger.info("证据包已导出: task_id=%s, by=%s", task_id, current_user.username)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": _disposition(f"监管取证证据包_任务{task_id}.zip")},
    )
