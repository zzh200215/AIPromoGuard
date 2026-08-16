"""审查任务编排服务：解析文档 → 后台跑 LangGraph workflow → 持久化结果与报告。

任务执行后端（B2）：
- 默认进程内线程池（MVP，免运维）；压测后升级为 Celery/Redis 队列。
- start_review 探测 Redis broker 上是否有 worker 存活（ping，30s 缓存）：
  有 → send_task 入队（worker 独占执行，api 不再跑审查，避免多进程并发写 ChromaDB）；
  无 → 回退线程池，保持单进程行为。
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import update

from src.core.agents.graph import run_review
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewBatch, ReviewResult, ReviewTask
from src.services.diff_service import build_review_blocks, diff_documents
from src.services.document_service import document_service
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)

# 系统自动确认标识（confirmed_by=0）：规则/双引擎高置信命中自动判违规，与人工复核区分。
_AUTO_CONFIRM_BY = 0
_AUTO_CONFIRM_SOURCES = {"rule", "hybrid"}

_QUEUE_BACKEND: str | None = None  # "celery" | "thread"
_LAST_CHECK = 0.0
_CHECK_TTL = 30.0


def _use_celery() -> bool:
    """探测 Celery worker 是否可用（ping，结果缓存 30s，避免每请求开销）。"""
    global _QUEUE_BACKEND, _LAST_CHECK
    now = time.monotonic()
    if _QUEUE_BACKEND and now - _LAST_CHECK < _CHECK_TTL:
        return _QUEUE_BACKEND == "celery"
    try:
        from src.infrastructure.queue.celery_app import celery_app

        workers = celery_app.control.ping(timeout=0.5)
        _QUEUE_BACKEND = "celery" if workers else "thread"
    except Exception:
        _QUEUE_BACKEND = "thread"
    _LAST_CHECK = now
    logger.info("审查队列后端: %s", _QUEUE_BACKEND)
    return _QUEUE_BACKEND == "celery"


def start_review(task_id: int) -> None:
    """提交审查任务：优先 Celery 队列，无 worker 时回退线程池。"""
    if _use_celery():
        from src.infrastructure.queue.celery_app import celery_app

        celery_app.send_task("review.run_review", args=[task_id], queue="review_tasks")
        return
    _executor.submit(execute_review, task_id)


def _update_batch_counts(db, task: ReviewTask) -> None:
    """任务到达终态后同步批次计数；无批次归属时直接返回。

    计数用原子 UPDATE 累加（多线程并发时读-改-写会丢失更新），
    提交后再读最新计数判断批次是否全部终态，置终态为幂等操作。
    """
    if not task.batch_id:
        return
    if db.get(ReviewBatch, task.batch_id) is None:
        return
    if task.status == "completed":
        db.execute(
            update(ReviewBatch)
            .where(ReviewBatch.id == task.batch_id)
            .values(completed_count=ReviewBatch.completed_count + 1)
        )
    elif task.status == "failed":
        db.execute(
            update(ReviewBatch)
            .where(ReviewBatch.id == task.batch_id)
            .values(failed_count=ReviewBatch.failed_count + 1)
        )
    else:
        return
    db.commit()

    batch = db.get(ReviewBatch, task.batch_id)
    if batch.completed_count + batch.failed_count >= batch.total_count:
        batch.status = "completed" if batch.failed_count == 0 else "failed"
        batch.completed_at = datetime.now()
        db.commit()


def _block_to_dict(block) -> dict:
    return {
        "text": block.text,
        "page": block.page,
        "paragraph": block.paragraph,
        "heading": block.heading,
    }


def execute_review(task_id: int) -> None:
    """执行一次完整审查（线程池与 Celery worker 共用入口）。"""
    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        if task is None:
            return
        task.status = "running"
        task.progress = 10
        task.started_at = datetime.now()
        db.commit()

        parsed = document_service.parse(task.document_path)
        blocks = [_block_to_dict(b) for b in parsed.blocks]
        diff_changes = None
        review_text = parsed.text
        review_blocks = blocks
        if task.base_document_path:
            # 对比模式：旧版解析 → diff → 只审变更块 + 上下文窗口
            base_parsed = document_service.parse(task.base_document_path)
            base_blocks = [_block_to_dict(b) for b in base_parsed.blocks]
            changes = diff_documents(base_blocks, blocks)
            diff_changes = [c.to_dict() for c in changes]
            task.diff_changes = diff_changes
            db.commit()
            review_blocks = build_review_blocks(blocks, changes)
            review_text = "\n".join(b["text"] for b in review_blocks)
        task.progress = 20
        db.commit()

        result = run_review(
            {
                "task_id": task.id,
                "document_path": task.document_path,
                "document_name": task.document_name,
                "doc_type": task.document_type,
                "text": review_text,
                "blocks": review_blocks,
                "diff_changes": diff_changes,
            }
        )

        report_data = result.get("report") or {}
        findings = report_data.get("violations", [])
        _persist_results(db, task.id, findings)

        task.stages = result.get("stage_log")  # 各 Agent 节点耗时（W14）
        task.report_path = result.get("report_path")
        task.report_path = result.get("report_path")
        task.status = "completed"
        task.progress = 100
        task.completed_at = datetime.now()
        db.commit()
        _update_batch_counts(db, task)
        logger.info("task %s 审查完成，命中 %s 条违规", task_id, len(findings))
    except Exception:
        db.rollback()
        task = db.get(ReviewTask, task_id)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            db.commit()
            _update_batch_counts(db, task)
        logger.exception("task %s 审查失败", task_id)
    finally:
        db.close()


def _auto_confirm(finding: dict, cfg: dict) -> tuple[str, datetime | None, int | None]:
    """人审分流：规则/双引擎高置信命中自动确认，其余进人工队列。

    - violation_type in (rule, hybrid) 且 confidence >= threshold → 自动 confirmed，
      confirmed_by=0（系统自动），confirmed_at 记录自动确认时刻。
    - 其余（纯 llm、低于阈值的 rule/hybrid）→ pending_confirm。
    - cfg 为空或 enabled=false 时全部 pending_confirm（开关回退）。
    """
    if not cfg.get("enabled", True):
        return "pending_confirm", None, None
    threshold = float(cfg.get("threshold", 0.85))
    vtype = str(finding.get("violation_type", "rule"))
    confidence = float(finding.get("confidence", 0))
    if vtype in _AUTO_CONFIRM_SOURCES and confidence >= threshold:
        return "confirmed", datetime.now(), _AUTO_CONFIRM_BY
    return "pending_confirm", None, None


def _persist_results(db, task_id: int, findings: list[dict]) -> None:
    auto_cfg = settings.app_config("workflow").get("auto_confirm", {})
    for item in findings:
        status, confirmed_at, confirmed_by = _auto_confirm(item, auto_cfg)
        db.add(
            ReviewResult(
                task_id=task_id,
                violation_type=item.get("violation_type", "rule")[:16],
                risk_level=item.get("risk_level", "low")[:8],
                original_text=(item.get("original_text") or "")[:2000],
                location_page=item.get("page"),
                location_paragraph=item.get("paragraph"),
                rule_id=item.get("rule_id"),
                confidence_score=item.get("confidence", 0),
                description=(item.get("description") or "")[:1000],
                suggestion=(item.get("suggestion") or "")[:1000],
                status=status,
                confirmed_at=confirmed_at,
                confirmed_by=confirmed_by,
            )
        )
