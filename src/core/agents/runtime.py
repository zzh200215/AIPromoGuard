"""带人工复核的图运行时：InMemorySaver checkpointer + interrupt 恢复。

thread_id 采用 f"review-task-{task_id}" 约定，API 侧恢复时无需为 HIL 增加
存储字段；graph 中断时把待复核清单返回给调用方（worker 置任务
awaiting_review），人工提交决策后 resume_review 从 checkpoint 续跑
risk_assess → report。

已知边界（部署说明）：InMemorySaver 仅进程内有效，适用线程池 worker 与
API 同进程的开发/演示形态；Celery worker 与 API 分进程部署时需替换为
持久化 checkpointer（MySQL / Redis 实现），接口不变。
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.core.agents.graph import build_graph

_SAVER = InMemorySaver()
_HIL_GRAPH = None


def get_hil_graph():
    global _HIL_GRAPH
    if _HIL_GRAPH is None:
        _HIL_GRAPH = build_graph(checkpointer=_SAVER)
    return _HIL_GRAPH


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
