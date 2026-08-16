"""Celery 应用（B2：压测后异步任务队列，替代 MVP 的进程内线程池）。

- broker/backend 默认取 settings.redis_url（Redis 已是 compose 常驻服务），
  可用 CELERY_BROKER_URL 环境变量覆盖。
- 任务在 src/infrastructure/queue/tasks.py，worker 启动:
    celery -A src.infrastructure.queue.celery_app worker -l info -Q review_tasks
- worker 与 api 使用同一镜像（fcr-api），共享 data/ 卷；由 worker 独占执行审查，
  api 仅入队，避免多进程并发访问 ChromaDB 持久化目录。
"""

from celery import Celery

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

QUEUE_REVIEW = "review_tasks"

_broker = settings.celery_broker_url or settings.redis_url

celery_app = Celery(
    "compliance_review",
    broker=_broker,
    backend=_broker,
    include=["src.infrastructure.queue.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,   # 任务一旦开始即可查询（PRD §11.3 状态追踪）
    task_default_queue=QUEUE_REVIEW,
)
