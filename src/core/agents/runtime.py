"""带人工复核的图运行时：MySQL 持久化 checkpointer + interrupt 恢复。

thread_id 采用 f"review-task-{task_id}" 约定，API 侧恢复时无需为 HIL 增加
存储字段；graph 中断时把待复核清单返回给调用方（worker 置任务
awaiting_review），人工提交决策后 resume_review 从 checkpoint 续跑
risk_assess → report。

checkpointer 用 MySQLCheckpointSaver（langgraph_checkpoints / langgraph_writes
表），checkpoint 跨进程、跨重启存活——API 或 worker 重启后 awaiting_review
任务仍可续跑，Celery 与 API 分进程部署同样成立。MySQL 不可用时回退
InMemorySaver（仅进程内有效，HIL 任务退化为不可跨进程 resume，由
review_service.start_review 守卫强制线程池兜底）。
"""

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.core.agents.graph import build_graph

logger = logging.getLogger(__name__)

_SAVER = None
_SAVER_PERSISTENT = False
_HIL_GRAPH = None


def _build_saver() -> tuple[object, bool]:
    """优先 MySQL 持久化 saver；DB 不可用时回退内存。返回 (saver, 是否持久)。"""
    try:
        from src.infrastructure.database.langgraph_saver import MySQLCheckpointSaver

        saver = MySQLCheckpointSaver()
        saver.setup()
        return saver, True
    except Exception as exc:
        logger.warning("MySQL checkpoint saver 不可用，回退 InMemorySaver：%s", exc)
        return InMemorySaver(), False


def get_hil_graph():
    global _HIL_GRAPH, _SAVER, _SAVER_PERSISTENT
    if _HIL_GRAPH is None:
        _SAVER, _SAVER_PERSISTENT = _build_saver()
        _HIL_GRAPH = build_graph(checkpointer=_SAVER)
    return _HIL_GRAPH


def saver_is_persistent() -> bool:
    """当前 checkpointer 是否跨进程持久（HIL 任务能否交给 Celery worker）。"""
    get_hil_graph()
    return _SAVER_PERSISTENT


def thread_id_for_task(task_id: int) -> str:
    return f"review-task-{task_id}"


def start_review_with_hil(initial_state: dict, thread_id: str) -> dict:
    """运行图直到完成或人工复核中断。

    返回:
        {"interrupted": True, "pending": [...待复核结论清单...]}
        {"interrupted": False, "result": <最终 state>}
    """
    config = {"configurable": {"thread_id": thread_id}}
    result = get_hil_graph().invoke(initial_state, config=config)
    interrupts = result.get("__interrupt__")
    if interrupts:
        # 单个 interrupt 节点时直接展开 payload（待复核结论清单）
        payloads = [i.value for i in interrupts]
        return {"interrupted": True, "pending": payloads[0] if len(payloads) == 1 else payloads}
    return {"interrupted": False, "result": result}


def resume_review(thread_id: str, decision: dict) -> dict:
    """注入人工决策（{"rejected_indexes": [...]}）并从 checkpoint 续跑到终点。"""
    config = {"configurable": {"thread_id": thread_id}}
    return get_hil_graph().invoke(Command(resume=decision), config=config)


def cleanup_task_checkpoints(task_id: int) -> None:
    """任务终态后清理 checkpoint 线程（仅持久化 saver 有东西可清）。"""
    if _SAVER_PERSISTENT and _SAVER is not None:
        try:
            _SAVER.delete_thread(thread_id_for_task(task_id))
        except Exception:
            logger.warning("task %s: checkpoint 清理失败（不影响任务结果）", task_id, exc_info=True)
