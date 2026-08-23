"""ConflictResolver：融合规则引擎与 LLM 双引擎结果（PRD §3.2.4）。

规则优先策略：规则引擎命中即权威采信；LLM 单独检出的违规标注"建议关注"；
规则与 LLM 均命中的合并为 hybrid（交叉验证，置信度提升）。
"""

from src.core.agents.state import ReviewState

# 规则 DSL 无违规性质字段，按 severity 推导（risk_assess 的类型权重需要）：
# high 规则（如"禁止刚性兑付"）语义上属禁止性，medium 属限制性，low 属披露性。
# 与 LLM 路的 type 字段同口径，避免规则命中被一律按披露性计分而系统性低估。
_SEVERITY_TYPE_MAP = {"high": "禁止性", "medium": "限制性", "low": "披露性"}


def _overlaps(a: str, b: str) -> bool:
    """两段证据是否指向同一处原文。

    含长度门槛：matched_text 是关键词 ±15/20 字的窗口，若无门槛，
    "保本" 这类短词落进任何规则的窗口都会被误标 hybrid（跨规则误配）。
    """
    if not a or not b:
        return False
    shorter = a if len(a) <= len(b) else b
    if len(shorter) < 4:
        return False
    return a in b or b in a


def conflict_resolve(state: ReviewState) -> dict:
    rule_hits = state.get("rule_hits", [])
    llm_findings = state.get("llm_findings", [])

    merged: list[dict] = []
    for hit in rule_hits:
        severity = hit.get("severity", "medium")
        merged.append(
            {
                "source": "rule",
                "violation_type": "rule",
                "type": _SEVERITY_TYPE_MAP.get(severity, "披露性"),
                "rule_id": hit.get("rule_id"),
                "rule_name": hit.get("rule_name"),
                "original_text": hit.get("matched_text", ""),
                "page": hit.get("page"),
                "paragraph": hit.get("paragraph"),
                "confidence": hit.get("confidence", 0.9),
                "severity": severity,
                "description": hit.get("description") or hit.get("rule_name", ""),
                "related_regulations": list(hit.get("related_regulations") or []),
            }
        )

    for item in llm_findings:
        original = item.get("original_text", "")
        confirmed = any(_overlaps(hit.get("matched_text", ""), original) for hit in rule_hits)
        merged.append(
            {
                "source": "hybrid" if confirmed else "llm",
                "violation_type": "hybrid" if confirmed else "llm",
                "type": item.get("type", "披露性"),
                "rule_id": None,
                "rule_name": item.get("issue", ""),
                "original_text": original,
                "page": item.get("page"),
                "paragraph": item.get("paragraph"),
                "confidence": item.get("confidence", 0.7),
                "severity": item.get("severity", "medium"),
                "description": item.get("reason", ""),
                "regulation": item.get("regulation"),
                "suggestion": item.get("suggestion"),
                "flag": None if confirmed else "建议关注",
            }
        )

    return {"merged_findings": merged}
