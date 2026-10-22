"""Celery 任务定义（B2）。

run_review_task: 执行一次完整审查，逻辑复用 review_service.execute_review
（原线程池入口，改名公开供 worker 调用；内部已含失败标记与日志）。
poll_regulation_updates: beat 定时抓取监管发布源，新法规进待确认列表。
patrol_published_materials: beat 定时发布后巡检（R3-1），changed/gone 触发复审或待跟进。
"""

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.queue.celery_app import celery_app
from src.services import content_patrol, regulation_monitor
from src.services.review_service import execute_review
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="review.run_review", queue="review_tasks", bind=True)
def run_review_task(self, task_id: int) -> None:
    """执行单次审查并持久化结果。task_id 为 review_tasks 主键。"""
    logger.info("[celery] 开始审查 task %s", task_id)
    execute_review(task_id)


@celery_app.task(name="regulation.poll_updates", queue="review_tasks")
def poll_regulation_updates() -> dict:
    """定时抓取监管发布源（beat 调度）：新法规进待确认列表，人工确认后才入库。"""
    db = SessionLocal()
    try:
        result = regulation_monitor.fetch_sources(db)
        logger.info(
            "[celery] 监管动态抓取完成：新增 %s，错误 %s",
            sum(s.get("new", 0) for s in result.get("sources", {}).values()),
            result.get("errors"),
        )
        return result
    finally:
        db.close()


@celery_app.task(name="patrol.published", queue="review_tasks")
def patrol_published_materials() -> dict:
    """发布后内容巡检（beat 调度，建议周期 7 天）：巡检台账登记的已发布渠道，
    与批准版内容指纹做双层判定（containment + 关键数字缺失）。

    注意：仅巡检「已授权自有渠道」（publish_url 登记在台账），不做第三方抓取。
    changed/gone 为需人工跟进的信号（自动创建复审任务或标记待更新）。
    """
    db = SessionLocal()
    try:
        result = content_patrol.patrol_materials(db)
        logger.info("[celery] 发布后巡检完成：%s", result.get("counts"))
        return result
    finally:
        db.close()
