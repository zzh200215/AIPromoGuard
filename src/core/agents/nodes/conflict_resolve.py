"""ConflictResolver：融合规则引擎与 LLM 双引擎结果（PRD §3.2.4）。

规则优先策略：规则引擎命中即权威采信；LLM 单独检出的违规标注"建议关注"；
规则与 LLM 均命中的合并为 hybrid（交叉验证，置信度提升）。
"""

from src.core.agents.state import ReviewState


def _overlaps(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a in b or b in a


def conflict_resolve(state: ReviewState) -> dict:
    rule_hits = state.get("rule_hits", [])
    llm_findings = state.get("llm_findings", [])

    merged: list[dict] = []
    for hit in rule_hits:
        merged.append(
            {
                "source": "rule",
                "violation_type": "rule",
                "rule_id": hit.get("rule_id"),
                "rule_name": hit.get("rule_name"),
                "original_text": hit.get("matched_text", ""),
                "page": hit.get("page"),
                "paragraph": hit.get("paragraph"),
                "confidence": hit.get("confidence", 0.9),
                "severity": hit.get("severity", "medium"),
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
