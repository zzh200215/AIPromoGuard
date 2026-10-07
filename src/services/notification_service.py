"""通知服务：关键事件落站内通知，尽力而为——通知失败绝不影响主流程。"""

from sqlalchemy.orm import Session

from src.models import Notification
from src.utils.logger import get_logger

logger = get_logger(__name__)


def notify(
    db: Session,
    user_id: int | None,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """写一条站内通知；user_id 为空或写库失败时静默跳过。"""
    if not user_id:
        return
    try:
        db.add(
            Notification(
                user_id=user_id,
                type=type,
                title=title[:255],
                body=body[:512] if body else None,
                link=link[:255] if link else None,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("站内通知写入失败: user=%s type=%s", user_id, type)


def notify_task_failed(db, task) -> None:
    """任务审查失败 → 通知创建人。"""
    notify(
        db,
        task.created_by,
        "task_failed",
        f"任务审查失败：{task.task_name}",
        body="常见原因：文档格式异常、依赖服务未就绪。可在任务详情页重试。",
        link=f"/tasks/{task.id}",
    )


def notify_batch_terminal(db, batch) -> None:
    """批次到达终态 → 通知创建人（成功/失败口径不同）。"""
    if batch.status == "completed":
        notify(
            db,
            batch.created_by,
            "batch_completed",
            f"批次审查完成：{batch.batch_name}",
            body=f"共 {batch.total_count} 个任务全部完成。",
            link=f"/batches/{batch.id}",
        )
    elif batch.status == "failed":
        notify(
            db,
            batch.created_by,
            "batch_failed",
            f"批次审查完成（含失败）：{batch.batch_name}",
            body=(
                f"成功 {batch.completed_count} / 失败 {batch.failed_count}，"
                "失败任务可在批次详情页一键重试。"
            ),
            link=f"/batches/{batch.id}",
        )
