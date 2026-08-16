"""HumanReview 节点：高风险结论的人工复核关卡（PRD §3.2 人工干预节点）。

LangGraph interrupt + checkpointer 实现的 human-in-the-loop：
- 命中待复核条件（severity ∈ review_severities 或 source ∈ review_sources，
  workflow.human_review 配置驱动）时调用 interrupt() 暂停整张图，
  把待复核清单交给人工；
- 人工经 Command(resume={"rejected_indexes": [...]}) 恢复执行，被否决的
  结论从 merged_findings 剔除，随后继续 risk_assess → report；
- 配置未启用或无待复核项时直通，行为与线性流程完全一致（默认关闭，
  既有 API 审查路径不受影响）。

interrupt() 依赖编译期注入 checkpointer（见 runtime.py InMemorySaver）；
Celery worker 与 API 分进程部署时需换成持久化 checkpointer（MySQL/Redis）。
"""

from langgraph.types import interrupt

from src.core.agents.state import ReviewState
from src.utils.config import settings


def _review_cfg() -> dict:
    return (settings.app_config("workflow").get("human_review") or {})


def _pending_indexes(findings: list[dict], severities: set, sources: set) -> list[int]:
    return [
        i
        for i, f in enumerate(findings)
        if f.get("severity") in severities or f.get("source") in sources
    ]


def human_review(state: ReviewState) -> dict:
    cfg = _review_cfg()
    if not cfg.get("enabled", False):
        return {}

    findings = state.get("merged_findings", [])
    severities = set(cfg.get("review_severities", ["high"]))
    sources = set(cfg.get("review_sources", ["hybrid"]))
    pending = _pending_indexes(findings, severities, sources)
    if not pending:
        return {"human_review": {"required": False, "rejected_indexes": []}}

    payload = [
        {
            "index": i,
            "source": findings[i].get("source"),
            "severity": findings[i].get("severity"),
            "description": findings[i].get("description"),
            "original_text": findings[i].get("original_text"),
        }
        for i in pending
    ]
    # 首次执行在此抛 GraphInterrupt 暂停图；恢复执行时返回人工决策 dict
    decision = interrupt(payload)

    rejected = set()
    if isinstance(decision, dict):
        rejected = {int(i) for i in decision.get("rejected_indexes") or []}
    kept = [f for i, f in enumerate(findings) if i not in rejected]
    return {
        "merged_findings": kept,
        "human_review": {
            "required": True,
            "rejected_indexes": sorted(rejected),
            "reviewed_count": len(pending),
        },
    }
