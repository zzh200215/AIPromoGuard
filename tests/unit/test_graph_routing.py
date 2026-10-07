"""领域条件路由（多 Agent 子图）测试：路由分派 + 图拓扑 + 兜底分支。"""

from langgraph.checkpoint.memory import InMemorySaver
from src.core.agents.graph import _domain_names, _route_by_domain, build_graph

# ---- 路由分派 ----

def test_route_by_domain_known():
    assert _route_by_domain({"domain": "banking"}) == "domain_banking"
    assert _route_by_domain({"domain": "fund"}) == "domain_fund"
    assert _route_by_domain({"domain": "insurance"}) == "domain_insurance"


def test_route_by_domain_none_falls_back_to_general():
    assert _route_by_domain({"domain": None}) == "domain_general"
    assert _route_by_domain({}) == "domain_general"


def test_route_by_domain_unknown_falls_back():
    # 未配置子图的新领域 → 兜底 general
    assert _route_by_domain({"domain": "trust"}) == "domain_general"


def test_domain_names_from_config():
    names = _domain_names()
    assert "banking" in names
    assert "fund" in names
    assert "insurance" in names


# ---- 图拓扑 ----

def _fresh_graph():
    # 传独立 checkpointer 规避 _GRAPH 缓存，保证每次构建独立拓扑
    return build_graph(checkpointer=InMemorySaver())


def _edges(src=None):
    graph = _fresh_graph().get_graph()
    edges = []
    for e in graph.edges:
        source = getattr(e, "source", None) or getattr(e, "start_node", None)
        target = getattr(e, "target", None) or getattr(e, "end_node", None)
        if src is None or source == src:
            edges.append((source, target))
    return edges


def test_graph_has_conditional_routing_from_classify():
    """classify 后存在到各领域子图 + 兜底分支的条件边（多 Agent 分派）。"""
    edges = _edges("classify")
    targets = {t for _, t in edges}
    assert "domain_banking" in targets
    assert "domain_fund" in targets
    assert "domain_insurance" in targets
    assert "domain_general" in targets


def test_graph_shared_chain_is_linear_after_conflict():
    """human_review → risk_assess → report → END 为严格线性，保证 HIL resume 可达。"""
    edges = _edges()
    assert ("human_review", "risk_assess") in edges
    assert ("risk_assess", "report") in edges
    assert ("report", "__end__") in edges


def test_all_domain_subgraphs_converge_to_human_review():
    """每个领域子图 + 兜底都无条件汇聚到 human_review（共享汇合链）。"""
    edges = _edges()
    seen = {t for s, t in edges if s in (
        "domain_banking", "domain_fund", "domain_insurance", "domain_general")}
    assert seen == {"human_review"}
