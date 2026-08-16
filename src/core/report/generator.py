"""结构化审查报告生成（PRD §3.2.8 五部分：任务信息 / 摘要 / 违规清单）。"""

from collections import Counter
from datetime import datetime


def build_report(
    task_id: int,
    document_name: str,
    domain: str | None,
    findings: list[dict],
    diff_changes: list[dict] | None = None,
    llm_usage: dict | None = None,
) -> dict:
    risk_counter = Counter(item.get("risk_level", "medium") for item in findings)
    report = {
        "report_version": "0.1",
        "task_id": task_id,
        "document_name": document_name,
        "domain": domain,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total_violations": len(findings),
            "high_risk": risk_counter.get("high", 0),
            "medium_risk": risk_counter.get("medium", 0),
            "low_risk": risk_counter.get("low", 0),
        },
        "violations": findings,
        "diff_changes": diff_changes or [],
    }
    if llm_usage:
        # LLM 成本观测：token 用量随报告落盘（未调用 LLM 时省略该字段）
        report["llm_usage"] = llm_usage
    return report
