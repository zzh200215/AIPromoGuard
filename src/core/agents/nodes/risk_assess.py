"""RiskAssessor：为每条融合后的违规评估风险等级（PRD §3.2.8 / §5.4.1）。

综合评分：违规类型（禁止性>限制性>披露性）+ 严重度 + 双引擎交叉权重 + 置信度
+ 知识图谱关联历史处罚案例佐证。
输出 risk_level 与 risk_reason（评估依据，供报告展示），并附 related_cases
（相似历史处罚案例，PRD 报告"关联处罚案例"章节数据源）。
"""

from src.core.agents.state import ReviewState
from src.services import graph_service

_TYPE_WEIGHT = {"禁止性": 3, "限制性": 2, "披露性": 1}
_SEVERITY_WEIGHT = {"high": 1, "medium": 0, "low": -1}

_GRAPH_CASES_TOP_K = 3
# W10 后 similar_cases 为三路加权融合分（量纲下移，强相关约 0.3+），阈值相应下调
_GRAPH_SIMILARITY_THRESHOLD = 0.25


def _assess(item: dict, cases: list[dict]) -> tuple[str, str]:
    vtype = item.get("type") or "披露性"
    severity = item.get("severity", "medium")
    source = item.get("source", "llm")
    try:
        confidence = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0

    score = _TYPE_WEIGHT.get(vtype, 1)
    reasons = [f"违规类型:{vtype}"]

    score += _SEVERITY_WEIGHT.get(severity, 0)
    reasons.append(f"严重度:{severity}")

    if source == "hybrid":
        score += 1
        reasons.append("规则+LLM双引擎确认")
    else:
        reasons.append(f"来源:{source}")

    if confidence >= 0.9:
        score += 1
        reasons.append("置信度高")

    # 知识图谱关联历史处罚案例佐证（PRD §5.4.1 Node 5）
    if cases:
        score += 1
        reasons.append(f"关联历史处罚案例{len(cases)}起")

    risk = "high" if score >= 4 else ("medium" if score >= 2 else "low")
    return risk, "; ".join(reasons)


def risk_assess(state: ReviewState) -> dict:
    findings = state.get("merged_findings", [])
    domain = state.get("domain")
    for item in findings:
        # 用违规点内容在图谱中检索相似历史案例（Neo4j 不可用时返回空，不影响流程）
        text = item.get("original_text") or item.get("rule_name") or item.get("description") or ""
        cases: list[dict] = []
        if text:
            try:
                cases = graph_service.similar_cases(text, domain, top_k=_GRAPH_CASES_TOP_K)
            except Exception:
                cases = []
        # 仅保留相似度达标的案例，避免弱匹配引入噪声
        relevant = [c for c in cases if c.get("similarity", 0) >= _GRAPH_SIMILARITY_THRESHOLD]
        item["related_cases"] = relevant
        risk, reason = _assess(item, relevant)
        item["risk_level"] = risk
        item["risk_reason"] = reason
    return {"merged_findings": findings}
