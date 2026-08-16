"""LangGraph 审查 workflow：解析在 service 层完成，本图从领域识别开始。

流程（PRD §3.2.7）：
    classify → regulation_match → (rule_scan ‖ llm_scan) → conflict_resolve
    → risk_assess → report

节点均经 _wrap 包装，记录各节点执行耗时到 state.stage_log（W14 状态追踪）。
"""

import time

from langgraph.graph import END, START, StateGraph

from src.core.agents.nodes.classify import classify
from src.core.agents.nodes.conflict_resolve import conflict_resolve
from src.core.agents.nodes.llm_scan import llm_scan
from src.core.agents.nodes.regulation_match import regulation_match
from src.core.agents.nodes.report import report
from src.core.agents.nodes.risk_assess import risk_assess
from src.core.agents.nodes.rule_scan import rule_scan
from src.core.agents.state import ReviewState
from src.core.llm.observability import get_llm_observer

_GRAPH = None

_NODES = [
    ("classify", classify),
    ("regulation_match", regulation_match),
    ("rule_scan", rule_scan),
    ("llm_scan", llm_scan),
    ("conflict_resolve", conflict_resolve),
    ("risk_assess", risk_assess),
    ("report", report),
]

_observer = get_llm_observer()


def _wrap(node, name: str):
    """包装节点：记录执行耗时，写入 stage_log（并行分支由 reducer 合并）。

    耗时同步上报 Langfuse（未配置时 no-op），形成节点级调用链观测。
    """

    def wrapped(state):
        start = time.monotonic()
        try:
            result = node(state) or {}
        except Exception:
            _observer.record_node(
                name, int((time.monotonic() - start) * 1000), "failed", state.get("task_id")
            )
            raise
        cost_ms = int((time.monotonic() - start) * 1000)
        result["stage_log"] = {name: {"status": "completed", "cost_ms": cost_ms}}
        _observer.record_node(name, cost_ms, "completed", state.get("task_id"))
        return result

    return wrapped


def build_graph():
    """构建并缓存编译后的图。rule_scan 与 llm_scan 并行，conflict_resolve 作为汇合点。"""
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    builder = StateGraph(ReviewState)
    for name, node in _NODES:
        builder.add_node(name, _wrap(node, name))

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "regulation_match")
    builder.add_edge("regulation_match", "rule_scan")
    builder.add_edge("regulation_match", "llm_scan")
    builder.add_edge("rule_scan", "conflict_resolve")
    builder.add_edge("llm_scan", "conflict_resolve")
    builder.add_edge("conflict_resolve", "risk_assess")
    builder.add_edge("risk_assess", "report")
    builder.add_edge("report", END)

    _GRAPH = builder.compile()
    return _GRAPH


def run_review(initial_state: dict) -> dict:
    return build_graph().invoke(initial_state)
