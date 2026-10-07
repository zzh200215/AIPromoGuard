"""LangGraph 审查 workflow：解析在 service 层完成，本图从领域识别开始。

流程（PRD §3.2.7）：
    classify → regulation_match → (rule_scan ‖ llm_scan) → conflict_resolve
    → human_review（interrupt 人工复核关卡，默认关闭直通）
    → risk_assess → report

节点均经 _wrap 包装，记录各节点执行耗时到 state.stage_log（W14 状态追踪）。
"""

import time

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph

from src.core.agents.nodes.classify import classify
from src.core.agents.nodes.conflict_resolve import conflict_resolve
from src.core.agents.nodes.human_review import human_review
from src.core.agents.nodes.llm_scan import llm_scan
from src.core.agents.nodes.regulation_match import regulation_match
from src.core.agents.nodes.report import report
from src.core.agents.nodes.risk_assess import risk_assess
from src.core.agents.nodes.rule_scan import rule_scan
from src.core.agents.state import ReviewState
from src.core.llm.observability import get_llm_observer
from src.utils.config import settings

_GRAPH = None

_NODES = [
    ("classify", classify),
    ("regulation_match", regulation_match),
    ("rule_scan", rule_scan),
    ("llm_scan", llm_scan),
    ("conflict_resolve", conflict_resolve),
    ("human_review", human_review),
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
        except GraphInterrupt:
            # 人工复核暂停不是失败：不落 stage_log（节点恢复重执行后会正常记录），
            # 仅在观测层标记 interrupted
            _observer.record_node(name, 0, "interrupted", state.get("task_id"))
            raise
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


def build_graph(checkpointer=None):
    """构建编译后的图。领域条件路由 + 领域子图 + 共享汇合链。

    classify 之后按 domain 用 add_conditional_edges 路由到独立领域子图
    （真·多 Agent 分工），每个子图内含 regulation_match → (rule_scan ∥ llm_scan)
    → conflict_resolve；领域无关的 human_review/risk_assess/report 作为共享
    汇合链保持线性（保证 HIL interrupt/resume 可达）。classify 识别失败
    （domain=None）或未知领域走 domain_general 兜底子图。

    checkpointer 用于 human_review 的 interrupt/resume（人工复核）：
    不传时图无暂停能力，human_review 未启用时行为等价（默认路径走缓存实例）。
    """
    global _GRAPH
    if checkpointer is None and _GRAPH is not None:
        return _GRAPH

    node_map = dict(_NODES)
    domain_names = _domain_names()

    def _build_domain_subgraph():
        sub = StateGraph(ReviewState)
        sub.add_node("regulation_match", _wrap(regulation_match, "regulation_match"))
        sub.add_node("rule_scan", _wrap(rule_scan, "rule_scan"))
        sub.add_node("llm_scan", _wrap(llm_scan, "llm_scan"))
        sub.add_node("conflict_resolve", _wrap(conflict_resolve, "conflict_resolve"))
        sub.add_edge(START, "regulation_match")
        sub.add_edge("regulation_match", "rule_scan")
        sub.add_edge("regulation_match", "llm_scan")
        sub.add_edge("rule_scan", "conflict_resolve")
        sub.add_edge("llm_scan", "conflict_resolve")
        sub.add_edge("conflict_resolve", END)
        return sub.compile()

    builder = StateGraph(ReviewState)
    # 领域无关的共享节点注册在主图最外层（只一次，避免子图/主图重名冲突）
    for name in ("classify", "human_review", "risk_assess", "report"):
        builder.add_node(name, _wrap(node_map[name], name))
    # 兜底 + 各领域子图
    builder.add_node("domain_general", _build_domain_subgraph())
    for d in domain_names:
        builder.add_node(f"domain_{d}", _build_domain_subgraph())

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        _route_by_domain,
        {"domain_general": "domain_general",
         **{f"domain_{d}": f"domain_{d}" for d in domain_names}},
    )
    # 共享汇合链：所有领域子图 → human_review → risk_assess → report → END（严格线性）
    builder.add_edge("domain_general", "human_review")
    for d in domain_names:
        builder.add_edge(f"domain_{d}", "human_review")
    builder.add_edge("human_review", "risk_assess")
    builder.add_edge("risk_assess", "report")
    builder.add_edge("report", END)

    compiled = builder.compile(checkpointer=checkpointer)
    if checkpointer is None:
        _GRAPH = compiled
    return compiled


def _domain_names() -> tuple[str, ...]:
    """从 app.yaml domains 读领域清单；缺省回退内置三领域。"""
    cfg = settings.app_config("domains") or {}
    return tuple(cfg.keys()) if cfg else ("banking", "fund", "insurance")


def _route_by_domain(state) -> str:
    """classify 之后按 domain 分派到独立领域子图；None/未知 → general 兜底。"""
    domain = state.get("domain")
    if domain in _domain_names():
        return f"domain_{domain}"
    return "domain_general"


def run_review(initial_state: dict) -> dict:
    return build_graph().invoke(initial_state)
