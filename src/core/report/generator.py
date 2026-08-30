"""结构化审查报告生成（PRD §3.2.8 五部分：任务信息 / 摘要 / 违规清单）。

成本归因：llm_usage 由 pricing 换算预估金额后随报告落盘。
待核验清单：证据门禁覆盖不到（引用缺失/未命中）或需业务材料佐证（适当性）
的存疑项显式聚合，供人工复核按单处理。
"""

from collections import Counter
from datetime import datetime

from src.core.llm.pricing import estimate_cost


def _pending_reasons(finding: dict) -> list[str]:
    """单条 finding 的待核验原因；空列表表示可自动背书，不进清单。"""
    reasons: list[str] = []
    source = finding.get("violation_type") or finding.get("source")
    if source == "vlm":
        reasons.append("视觉层判断基于图像排版/图形暗示，需人工对照原图确认")
    elif finding.get("evidence_supported") is False:
        reasons.append("引用法规未在召回条款中命中，需人工核对法规原文")
    elif finding.get("evidence_supported") is None and source in ("llm", "hybrid"):
        reasons.append("未附法规引用或召回条款为空，自动证据核验未覆盖")
    haystack = "".join(
        finding.get(key) or "" for key in ("type", "rule_name", "description")
    )
    if "适当性" in haystack:
        reasons.append("适当性判定需对照产品风险等级与目标客群材料")
    return reasons


def collect_pending_verification(findings: list[dict]) -> list[dict]:
    """待人工核验清单：机器无法闭环背书的存疑项，按风险降序。"""
    items = [
        {
            "risk_level": f.get("risk_level"),
            "original_text": (f.get("original_text") or "")[:200],
            "description": f.get("rule_name") or f.get("description"),
            "page": f.get("page"),
            "paragraph": f.get("paragraph"),
            "reasons": _pending_reasons(f),
        }
        for f in findings
        if _pending_reasons(f)
    ]
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: order.get(x["risk_level"], 3))
    return items


def build_report(
    task_id: int,
    document_name: str,
    domain: str | None,
    findings: list[dict],
    diff_changes: list[dict] | None = None,
    llm_usage: dict | None = None,
    profile: str | None = None,
) -> dict:
    risk_counter = Counter(item.get("risk_level", "medium") for item in findings)
    summary = {
        "total_violations": len(findings),
        "high_risk": risk_counter.get("high", 0),
        "medium_risk": risk_counter.get("medium", 0),
        "low_risk": risk_counter.get("low", 0),
    }
    report = {
        "report_version": "0.1",
        "task_id": task_id,
        "document_name": document_name,
        "domain": domain,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "violations": findings,
        "diff_changes": diff_changes or [],
    }
    if llm_usage:
        # LLM 成本观测：token 用量 + 牌价预估随报告落盘（未调用 LLM 时省略该字段）
        enriched = dict(llm_usage)
        enriched.update(estimate_cost(llm_usage, llm_usage.get("model")))
        report["llm_usage"] = enriched
    pending = collect_pending_verification(findings)
    report["pending_verification"] = pending
    summary["pending_verification"] = len(pending)
    if profile:
        report["profile"] = profile
    return report
