"""低危修复回归：.doc 拒绝 / 全角正则归一 / 报告 None 页码 / hybrid 短重叠门槛。"""

import pytest
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown
from src.parsers import get_parser
from src.utils.errors import AppError


def test_doc_extension_rejected_with_hint():
    """旧版 .doc 在解析分发层被拒并给出转换提示（python-docx 打不开必失败）。"""
    with pytest.raises(AppError, match="另存为"):
        get_parser("旧文件.doc")
    assert get_parser("新文件.docx").__class__.__name__ == "DocxParser"


def test_regex_matcher_fullwidth_digits():
    """全角"１００％"归一后命中 \\d+% 模式，且偏移与原文等长对齐。"""
    from src.core.rule_engine.matchers.regex_matcher import RegexMatcher

    m = RegexMatcher()
    spans = m.match("预期年化收益１００％稳赚", {"type": "regex", "pattern": r"\d+(\.\d+)?%"})
    assert spans and spans[0].text == "100%"

    text = "收益１００％"
    hit = m.match(text, {"type": "regex", "pattern": r"\d+%"})[0]
    assert text[hit.start : hit.end] == "１００％"


def test_render_markdown_none_page_shows_placeholder():
    """page/paragraph 为 None（txt/docx 块）时渲染占位符而不是"第None页"。"""
    report = build_report(
        1,
        "测试产品.txt",
        "banking",
        [
            {
                "source": "llm",
                "risk_level": "medium",
                "rule_name": "风险提示不充分",
                "original_text": "历史业绩不代表未来",
                "page": None,
                "paragraph": None,
            }
        ],
    )
    md = render_markdown(report)
    assert "第-页/第-段" in md
    assert "None" not in md


def test_overlaps_short_fragment_not_hybrid():
    """短片段（<4 字）落进规则窗口不判 hybrid，防跨规则误配虚增置信度。"""
    from src.core.agents.nodes.conflict_resolve import conflict_resolve

    state = {
        "rule_hits": [
            {
                "rule_id": 1,
                "rule_name": "禁止保本保收益",
                "matched_text": "本产品保本保收益放心买",
                "page": 1,
                "paragraph": 1,
                "confidence": 0.9,
                "severity": "high",
            }
        ],
        "llm_findings": [
            # "稳赚" 仅 2 字：包含于规则窗口但指向不同违规
            {"issue": "稳赚表述", "original_text": "稳赚", "severity": "low", "reason": "r"},
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[1]["source"] == "llm"
