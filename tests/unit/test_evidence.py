"""证据核验交接关卡测试：引用可支撑性三态 + 批量标注 + 报告可见。

citation_supported 从评估工具（judge.py）提炼进生产流（evidence 服务），
conflict_resolve 对 llm/hybrid 结论逐条核验；evidence_supported=False 的
结论不允许自动确认（_auto_confirm 闸门，test_auto_confirm.py 另有覆盖）。
"""

from src.core.report.markdown import render_markdown
from src.services import evidence


def _article(name: str) -> dict:
    return {"regulation_name": name, "article_no": "第二十六条", "content": "x"}


def test_citation_supported_bracket_match():
    articles = [_article("互联网保险业务监管办法")]
    assert (
        evidence.citation_supported(
            {"regulation": "《互联网保险业务监管办法》第二十六条"}, articles
        )
        is True
    )
    assert evidence.citation_supported({"regulation": "《不存在的办法》第五条"}, articles) is False


def test_citation_supported_substring_fallback():
    articles = [_article("互联网保险业务监管办法")]
    # 无书名号：召回法规名出现在引用文本中即支撑
    assert (
        evidence.citation_supported(
            {"regulation": "根据互联网保险业务监管办法第二十六条"}, articles
        )
        is True
    )
    # 泛引（找不到任何召回法规名）→ 不可支撑
    assert evidence.citation_supported({"regulation": "根据监管机构相关规定"}, articles) is False


def test_citation_supported_none_cases():
    articles = [_article("互联网保险业务监管办法")]
    assert evidence.citation_supported({"regulation": ""}, articles) is None  # 未引用
    assert evidence.citation_supported({"regulation": "某办法"}, articles) is None  # 短引用不判
    assert evidence.citation_supported({"regulation": "《某办法》第五条"}, []) is None  # 召回为空


def test_annotate_evidence_in_place():
    articles = [_article("互联网保险业务监管办法")]
    findings = [
        {"regulation": "《互联网保险业务监管办法》第二十六条"},
        {"regulation": "《不存在的办法》"},
        {"regulation": ""},
    ]
    out = evidence.annotate_evidence(findings, articles)
    assert out[0]["evidence_supported"] is True
    assert out[1]["evidence_supported"] is False
    assert out[2]["evidence_supported"] is None


def test_markdown_flags_unsupported_evidence():
    """证据不可支撑的结论在 Markdown 报告中带 ⚠️证据待核 标记。"""
    report = {
        "summary": {"total_violations": 1, "high_risk": 0},
        "violations": [
            {
                "source": "llm",
                "risk_level": "high",
                "type": "禁止性",
                "confidence": 0.9,
                "rule_name": "收益承诺",
                "page": 1,
                "paragraph": 2,
                "original_text": "保本保收益",
                "suggestion": "删除承诺表述",
                "evidence_supported": False,
            }
        ],
    }
    md = render_markdown(report)
    assert "⚠️证据待核" in md
    # 证据正常/规则路结论不带标记
    report["violations"][0]["evidence_supported"] = True
    assert "⚠️证据待核" not in render_markdown(report)
