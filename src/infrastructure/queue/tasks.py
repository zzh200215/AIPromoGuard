"""Celery 任务定义（B2）。

run_review_task: 执行一次完整审查，逻辑复用 review_service.execute_review
（原线程池入口，改名公开供 worker 调用；内部已含失败标记与日志）。
"""

from src.infrastructure.queue.celery_app import celery_app
from src.services.review_service import execute_review
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="review.run_review", queue="review_tasks", bind=True)
def run_review_task(self, task_id: int) -> None:
    """执行单次审查并持久化结果。task_id 为 review_tasks 主键。"""
    logger.info("[celery] 开始审查 task %s", task_id)
    execute_review(task_id)
