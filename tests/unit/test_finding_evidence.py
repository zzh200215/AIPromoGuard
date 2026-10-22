"""结论级证据补检（per-finding evidence）的单测。

背景（2026-10-22 实测）：`regulation_match` 只按整篇材料检索一次，5 条召回被所有
结论共用——一份直播话术材料的 9 条结论全引同一部办法同一条；而对口的法规虽被召回，
却因为"不在共用池里"被判证据待核。这里锁住三条契约：
1. 每条结论各自检索、各自挂依据；
2. 补检结果并入全局证据池（按 法规名+条号 去重）；
3. 不改写 LLM 自己写的 regulation（可追溯）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services import evidence  # noqa: E402


def _art(reg: str, art: str, score: float = 0.8) -> dict:
    return {"regulation_name": reg, "article_no": art, "score": score}


def test_attach_writes_per_finding_labels():
    findings = [
        {"original_text": "保本保收益", "regulation": "甲办法 第一条"},
        {"original_text": "稳赚不赔"},
    ]
    per = [[_art("乙办法", "第三条")], [_art("丙办法", "第五条"), _art("丁办法", "第九条")]]
    evidence.attach_finding_evidence(findings, per)
    assert findings[0]["related_regulations"] == ["《乙办法》第三条"]
    assert findings[1]["related_regulations"] == ["《丙办法》第五条", "《丁办法》第九条"]


def test_attach_does_not_overwrite_llm_regulation():
    findings = [{"original_text": "x", "regulation": "原引用办法 第二条"}]
    evidence.attach_finding_evidence(findings, [[_art("新依据办法", "第一条")]])
    assert findings[0]["regulation"] == "原引用办法 第二条"


def test_attach_skips_empty_hits():
    findings = [{"original_text": "x"}]
    evidence.attach_finding_evidence(findings, [[]])
    assert "related_regulations" not in findings[0]


def test_attach_merges_existing_related_regulations():
    findings = [{"original_text": "x", "related_regulations": ["《旧办法》第一条"]}]
    evidence.attach_finding_evidence(findings, [[_art("新办法", "第二条")]])
    assert findings[0]["related_regulations"] == ["《旧办法》第一条", "《新办法》第二条"]


def test_retrieve_for_findings_returns_aligned_list(monkeypatch):
    """检索抛异常时该条为空列表，不中断整批（对齐长度）。"""
    from src.services import regulation_service

    def _boom(*_a, **_k):
        raise RuntimeError("向量库不可用")

    monkeypatch.setattr(regulation_service, "search_semantic", _boom)
    out = evidence.retrieve_for_findings([{"original_text": "保本保收益"}])
    assert out == [[]]
