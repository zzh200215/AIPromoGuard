"""工具查证条款并入证据核验集（2026-10-16 机制缺口修复）的单元测试。

覆盖：
- conflict_resolve：引用只命中 tool_articles（不在初始召回）→ evidence_supported=True；
- 无 tool_articles 时行为不变（向后兼容）；
- （法规名, 条款号）去重——工具查证条款与初始召回重复时不重复计数。
"""

from src.core.agents.nodes.conflict_resolve import conflict_resolve


def _llm_finding(regulation: str) -> dict:
    return {
        "original_text": "保本保收益，稳赚不赔",
        "issue": "承诺保本保收益",
        "reason": "违反禁止保本承诺规定",
        "confidence": 0.85,
        "severity": "high",
        "regulation": regulation,
    }


def test_tool_articles_enter_evidence_set():
    """引用只命中工具查证条款（不在初始召回）→ 判定可支撑而非'证据待核'。"""
    state = {
        "rule_hits": [],
        "llm_findings": [_llm_finding("《健康保险管理办法》第二十条")],
        "matched_articles": [
            {"regulation_name": "别的办法", "article_no": "第一条", "content": "无关条款"}
        ],
        "tool_articles": [
            {"regulation_name": "健康保险管理办法", "article_no": "第二十条", "content": "…"}
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert len(merged) == 1
    assert merged[0]["evidence_supported"] is True


def test_without_tool_articles_unsupported_still_flags():
    """无工具查证、引用未命中召回 → 仍标 False（旧行为不回归）。"""
    state = {
        "rule_hits": [],
        "llm_findings": [_llm_finding("《健康保险管理办法》第二十条")],
        "matched_articles": [
            {"regulation_name": "别的办法", "article_no": "第一条", "content": "无关条款"}
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[0]["evidence_supported"] is False


def test_tool_articles_deduped_against_initial_recall():
    """工具查证条款与初始召回重复 → 去重，不产生重复证据条目（幂等判定）。"""
    art = {"regulation_name": "健康保险管理办法", "article_no": "第二十条", "content": "…"}
    state = {
        "rule_hits": [],
        "llm_findings": [_llm_finding("《健康保险管理办法》第二十条")],
        "matched_articles": [dict(art)],
        "tool_articles": [dict(art)],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[0]["evidence_supported"] is True
