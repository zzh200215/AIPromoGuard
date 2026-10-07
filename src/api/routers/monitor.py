"""系统监控指标端点（W16，PRD §3.2.9 监控告警）。

返回任务统计、数据库连通、向量库规模、知识图谱状态、近期操作审计。
仅 monitor 权限（admin）可访问。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.api.middleware.auth import require_permission
from src.infrastructure.database.mysql import get_db
from src.models import AuditLog, Regulation, ReviewTask, Rule, User
from src.services import graph_service
from src.utils.config import settings
from src.utils.response import ok

router = APIRouter(prefix="/system", tags=["system"])


def _vector_counts() -> dict:
    try:
        from src.infrastructure.vectorstore import get_vector_store

        store = get_vector_store()
        prefix = settings.app_config("vectorstore").get("collection_prefix", "legal_")
        return {
            "legal_articles": store.count(prefix + "articles"),
            "legal_penalty_cases": store.count(prefix + "penalty_cases"),
        }
    except Exception:
        return {"legal_articles": -1, "legal_penalty_cases": -1}


def _celery_status() -> dict:
    """Celery 队列状态（尽力而为）：待处理任务数 + worker 存活列表。

    失败一律返回 available=false，不影响监控主接口；Redis 不可用时队列深度为 -1。
    """
    result: dict = {"available": False, "queue_depth": -1, "workers_alive": []}
    try:
        import redis as redis_lib

        from src.infrastructure.queue.celery_app import QUEUE_REVIEW, celery_app

        client = redis_lib.Redis.from_url(settings.celery_broker_url or settings.redis_url)
        result["queue_depth"] = client.llen(QUEUE_REVIEW)
        ping = celery_app.control.inspect(timeout=1.0).ping()
        result["workers_alive"] = sorted(ping.keys()) if ping else []
        result["available"] = True
    except Exception:
        return result
    return result


@router.get("/monitor")
def system_monitor(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("monitor")),
) -> dict:
    """系统监控：任务/数据库/向量库/图谱/队列/审计六类指标。"""
    # 1. 任务统计
    status_rows = (
        db.query(ReviewTask.status, func.count(ReviewTask.id))
        .group_by(ReviewTask.status)
        .all()
    )
    task_stats = {s: c for s, c in status_rows}
    day_ago = datetime.now() - timedelta(hours=24)
    tasks_24h = db.query(ReviewTask).filter(ReviewTask.created_at >= day_ago).count()
    avg_ms = (
        db.query(
            func.avg(
                func.timestampdiff(text("SECOND"), ReviewTask.started_at, ReviewTask.completed_at)
            )
        )
        .filter(ReviewTask.status == "completed", ReviewTask.started_at.isnot(None))
        .scalar()
    )

    # 2. 数据库连通与知识库规模
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    kb = {
        "regulations": db.query(Regulation).count(),
        "rules": db.query(Rule).count(),
        "users": db.query(User).count(),
    }

    # 3. 向量库
    vectors = _vector_counts()

    # 4. 知识图谱（Neo4j）
    graph = graph_service.graph_stats()

    # 5. Celery 队列（worker 未启用时 available=false）
    celery = _celery_status()

    # 6. 审计
    audit_24h = db.query(AuditLog).filter(AuditLog.created_at >= day_ago).count()
    recent_errors = (
        db.query(AuditLog)
        .filter(AuditLog.created_at >= day_ago, AuditLog.status_code >= 400)
        .count()
    )

    return ok(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "tasks": {
                **task_stats,
                "last_24h": tasks_24h,
                "avg_duration_seconds": round(avg_ms, 1) if avg_ms is not None else None,
            },
            "database": {"ok": db_ok, "knowledge_base": kb},
            "vector_store": vectors,
            "graph": graph,
            "celery": celery,
            "audit": {"last_24h": audit_24h, "errors_last_24h": recent_errors},
        }
    )
