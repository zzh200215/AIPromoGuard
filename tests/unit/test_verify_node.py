"""Verifier 节点测试（第 3 批：生成-验证对偶）——全离线，LLM 打桩。

覆盖：功能开关 / LLM 未配置 / 批量验证三态应用（维持·降级·剔除）/
低置信驳回按降级处理（宁少杀不错杀）/ 失败降级原样保留 / 非 llm 来源不验证 /
混合来源列表剔除后其余结论原序保留。
"""

import json
from types import SimpleNamespace

import pytest
from src.core.agents.nodes import verify as verify_mod
from src.core.agents.nodes.verify import verify


def _finding(source="llm", confidence=0.8, original="本产品保本保收益"):
    return {
        "source": source,
        "violation_type": "llm" if source == "llm" else source,
        "rule_name": "疑似承诺保本",
        "original_text": original,
        "confidence": confidence,
        "severity": "high",
        "description": "承诺保本",
        "regulation": "《资管新规》第十九条",
        "flag": "建议关注",
    }


class _StubLLM:
    model = "stub"

    def __init__(self, content=None, fail=False):
        self.content = content
        self.fail = fail
        self.calls = []

    def complete(self, messages, temperature=None):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("llm down")
        return SimpleNamespace(content=self.content, usage=None)


def _verdicts(items):
    return json.dumps(
        {"verdicts": [{"index": i, **v} for i, v in enumerate(items)]},
        ensure_ascii=False,
    )


@pytest.fixture()
def verifier_on(monkeypatch):
    """打开 verifier 开关（settings 是 pydantic 模型，patch 模块级 _cfg 而非方法）。"""
    monkeypatch.setattr(
        verify_mod, "_cfg", lambda: {**verify_mod._DEFAULTS, "verifier": True}
    )


def _run(state, llm):
    import src.core.agents.nodes.verify as vm

    orig = vm.get_llm
    vm.get_llm = lambda: llm
    try:
        return verify(state)
    finally:
        vm.get_llm = orig


def test_disabled_by_default_is_noop():
    out = verify({"merged_findings": [_finding()]})
    assert out == {}  # 缺省关：state 不动


def test_llm_off_skips(verifier_on):
    out = _run({"merged_findings": [_finding()]}, llm=None)
    assert out == {"verification_meta": {"skipped": "llm_off"}}


def test_upheld_downgraded_rejected_applied(verifier_on):
    findings = [
        _finding(original="保本保收益", confidence=0.9),
        _finding(original="收益还不错", confidence=0.7),
        _finding(original="业绩比较基准描述", confidence=0.8),
    ]
    out = _run(
        {"merged_findings": findings},
        _StubLLM(
            _verdicts([
                {"verdict": "upheld", "confidence": 0.9, "reason": "成立"},
                {"verdict": "downgraded", "confidence": 0.6, "reason": "判罚过重"},
                {"verdict": "rejected", "confidence": 0.95, "reason": "合规披露"},
            ])
        ),
    )
    kept = out["merged_findings"]
    assert len(kept) == 2  # 高置信 rejected 被剔除
    assert kept[0]["original_text"] == "保本保收益"
    assert kept[0]["verification"]["verdict"] == "upheld"
    assert kept[0]["confidence"] == 0.9  # 维持不动 confidence
    assert kept[1]["original_text"] == "收益还不错"
    assert kept[1]["confidence"] == pytest.approx(0.7 * 0.8, abs=1e-3)  # 降级 ×0.8
    meta = out["verification_meta"]
    assert meta["verified"] == 3 and meta["upheld"] == 1
    assert meta["downgraded"] == 1 and meta["rejected_dropped"] == 1
    assert meta["dropped"][0]["original_text"].startswith("业绩比较基准")


def test_low_confidence_rejection_downgrades_instead(verifier_on):
    """驳回但验证置信度不足 → 不剔除只降级（宁少杀不错杀）。"""
    findings = [_finding(confidence=0.8)]
    out = _run(
        {"merged_findings": findings},
        _StubLLM(_verdicts([{"verdict": "rejected", "confidence": 0.5, "reason": "疑似合规"}])),
    )
    # 无剔除 → 不返回 merged_findings（降级经共享引用原地生效）
    assert "merged_findings" not in out
    assert len(findings) == 1
    assert findings[0]["confidence"] == pytest.approx(0.8 * 0.8, abs=1e-3)
    assert out["verification_meta"]["rejected_kept"] == 1
    assert out["verification_meta"]["rejected_dropped"] == 0


def test_call_failure_keeps_findings(verifier_on):
    findings = [_finding(), _finding(original="第二条 llm 判定")]
    out = _run({"merged_findings": findings}, _StubLLM(fail=True))
    # 失败降级：不返回 merged_findings（图 state 保持原值），仅 meta 计数
    assert "merged_findings" not in out
    meta = out["verification_meta"]
    assert meta["failed"] == 1 and meta["verified"] == 0


def test_unparseable_output_keeps_findings(verifier_on):
    out = _run({"merged_findings": [_finding()]}, _StubLLM("完全不是 JSON 的输出"))
    assert "merged_findings" not in out
    assert out["verification_meta"]["failed"] >= 1


def test_only_llm_source_verified(verifier_on):
    findings = [
        _finding(source="rule"),
        _finding(source="hybrid"),
        _finding(source="llm"),
    ]
    llm = _StubLLM(_verdicts([{"verdict": "upheld", "confidence": 0.9, "reason": "ok"}]))
    out = _run({"merged_findings": findings}, llm)
    # 无剔除 → 不返回 merged_findings，原列表原地未动（仅 llm 条获得 verification）
    assert "merged_findings" not in out
    assert len(findings) == 3
    assert "verification" not in findings[0] and "verification" not in findings[1]
    assert findings[2]["verification"]["verdict"] == "upheld"
    # 批量消息只含 1 条待验证判定（index 0 对应 targets[0]）
    assert llm.calls[0][1]["content"].count("原文：") == 1


def test_build_verifier_messages_shape():
    from src.core.llm.prompts.verifier import build_verifier_messages

    msgs = build_verifier_messages([_finding(), _finding(original="第二条")])
    assert msgs[0]["role"] == "system" and "独立验证员" in msgs[0]["content"]
    assert msgs[1]["content"].count("原文：") == 2
    assert "0." in msgs[1]["content"] and "1." in msgs[1]["content"]
