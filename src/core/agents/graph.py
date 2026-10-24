"""LangGraph 审查 workflow：解析在 service 层完成，本图从领域识别开始。

流程（PRD §3.2.7）：
    classify → regulation_match → (rule_scan ‖ llm_scan) → conflict_resolve
    → human_review（interrupt 人工复核关卡，默认关闭直通）
    → risk_assess → report

节点均经 _wrap 包装，记录各节点执行耗时到 state.stage_log（W14 状态追踪）；
同时把节点增量结果里的过程明细经 _stage_detail 搬进 stage_log.detail
（审查轨迹面板数据源——召回条款数 / 工具查证 token / 双引擎融合分布等，
全部来自 state 已有数据，不新增计算；体积护栏：只留计数与 top-N 名称）。
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
from src.core.agents.nodes.verify import verify
from src.core.agents.state import ReviewState
from src.core.llm.observability import get_llm_observer
from src.core.llm.prompts.registry import get_prompt
from src.utils.config import settings

_GRAPH = None

_NODES = [
    ("classify", classify),
    ("regulation_match", regulation_match),
    ("rule_scan", rule_scan),
    ("llm_scan", llm_scan),
    ("conflict_resolve", conflict_resolve),
    ("verify", verify),
    ("human_review", human_review),
    ("risk_assess", risk_assess),
    ("report", report),
]

_observer = get_llm_observer()

_TOP_ARTICLES = 3  # top-N 条款名截断（stage_log 落 MySQL JSON 列，控体积）


def _stage_detail(name: str, result: dict) -> dict | None:
    """从节点增量结果提取过程明细（前端审查轨迹面板消费）。

    数据来源全部是各节点已经产出的 state 增量（result），这里只做形状整理：
    无新计算、无 DB 查询、无副作用；异常安全（节点返回缺键时静默省略）。
    """
    if name == "classify":
        return {"domain": result.get("domain")}

    if name == "regulation_match":
        articles = result.get("matched_articles") or []
        detail: dict = {
            "article_count": len(articles),
            "top_articles": [
                {
                    "name": (a.get("regulation_name") or "")[:60],
                    "article_no": a.get("article_no"),
                }
                for a in articles[:_TOP_ARTICLES]
            ],
        }
        # P3 Agentic RAG（可选开启时才有）：补检轮次与新增条款数
        meta = result.get("retrieval_meta") or {}
        if meta.get("rounds"):
            detail["agentic_rounds"] = meta.get("rounds")
            detail["agentic_added"] = meta.get("added", 0)
        return detail

    if name == "rule_scan":
        return {"hit_count": len(result.get("rule_hits") or [])}

    if name == "llm_scan":
        usage = result.get("llm_usage") or {}
        return {
            "finding_count": len(result.get("llm_findings") or []),
            "tokens": usage.get("total_tokens"),
            "failed_blocks": usage.get("failed_blocks"),
            "model": usage.get("model"),
            # prompt 版本审计：审查结论可溯源到 prompt 注册表的具体版本
            "prompt": f"review@{get_prompt('review').version}",
            # 先例记忆可观测：本任务注入的历史人工判定先例数（0=无记忆可用）
            "precedents": (result.get("precedent_meta") or {}).get("injected", 0),
            # 执行通道（第 4 批）：standard / deep / light / none
            "channel": (result.get("scan_meta") or {}).get("channel", "standard"),
        }

    if name == "conflict_resolve":
        merged = result.get("merged_findings") or []
        by_source: dict[str, int] = {}
        for f in merged:
            src = f.get("source") or "unknown"
            by_source[src] = by_source.get(src, 0) + 1
        return {"merged_count": len(merged), "by_source": by_source}

    if name == "verify":
        meta = result.get("verification_meta") or {}
        if not meta:
            return {}
        detail = {"verified": meta.get("verified", 0)}
        for k in ("upheld", "downgraded", "rejected_dropped", "failed"):
            if meta.get(k):
                detail[k] = meta[k]
        return detail or None
    if name == "human_review":
        hr = result.get("human_review")
        if not hr:
            # 节点直通（关卡未启用/profile=loose）：标记未启用
            return {"enabled": False}
        return {
            "enabled": True,
            "required": bool(hr.get("required")),
            "reviewed_count": hr.get("reviewed_count", 0),
            "rejected_count": len(hr.get("rejected_indexes") or []),
        }

    if name == "risk_assess":
        findings = result.get("merged_findings") or []
        by_risk: dict[str, int] = {}
        with_cases = 0
        for f in findings:
            level = f.get("risk_level") or "unknown"
            by_risk[level] = by_risk.get(level, 0) + 1
            if f.get("related_cases"):
                with_cases += 1
        return {"by_risk": by_risk, "with_cases": with_cases}

    if name == "report":
        summary = (result.get("report") or {}).get("summary") or {}
        return {"total_violations": summary.get("total_violations")}

    return None


def _flush_stage(task_id, name: str, entry: dict) -> None:
    """节点完成即增量落库（审查轨迹实时化，stage_sink）：任何失败静默。"""
    if not task_id:
        return
    try:
        from src.services.stage_sink import persist_stage

        persist_stage(task_id, name, entry)
    except Exception:
        pass  # 侧信道绝不阻断审查主流程；完成时 _finalize_task 整体覆盖兜底


def _wrap(node, name: str):
    """包装节点：记录执行耗时，写入 stage_log（并行分支由 reducer 合并）。

    耗时同步上报 Langfuse（未配置时 no-op），形成节点级调用链观测。
    过程明细（detail）随 stage_log 落库，供前端审查轨迹面板展示；
    每个节点成功完成即经 stage_sink 增量合并落库——运行中轨迹逐节点
    可见（2026-10-15 实时化修复），完成后由 _finalize_task 整体覆盖定稿。
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
        entry: dict = {"status": "completed", "cost_ms": cost_ms}
        detail = _stage_detail(name, result)
        if detail is not None:
            entry["detail"] = detail
        result["stage_log"] = {name: entry}
        _flush_stage(state.get("task_id"), name, entry)
        _observer.record_node(name, cost_ms, "completed", state.get("task_id"))
        return result

    return wrapped


def build_graph(checkpointer=None):
    """构建编译后的图。领域条件路由 + 领域子图 + 共享汇合链。

    classify 之后按 domain 用 add_conditional_edges 路由到独立领域子图
    （真·多 Agent 分工），每个子图内含 regulation_match → (rule_scan ∥ llm_scan)
    → conflict_resolve → verify（可选 verifier 独立复核）；领域无关的
    human_review/risk_assess/report 作为共享
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
    for name in ("classify", "verify", "human_review", "risk_assess", "report"):
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
    builder.add_edge("domain_general", "verify")
    for d in domain_names:
        builder.add_edge(f"domain_{d}", "verify")
    builder.add_edge("verify", "human_review")
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
