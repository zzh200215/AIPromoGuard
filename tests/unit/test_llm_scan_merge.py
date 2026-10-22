"""llm_scan 的"小段合并成扫描单元"契约。

背景（2026-10-22 实测）：llm_scan 原按段落逐块调用 LLM，583 字的营销话术被切成 6 段
→ 6 次串行调用（每次 20-160s，其中 1.4k tokens 是固定系统提示）。真实材料几十段时
审查时间以小时计。合并后调用数与段落数解耦，且结论仍能定位回原段落。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.core.agents.nodes.llm_scan as mod  # noqa: E402


def _b(i: int, text: str | None = None, heading: bool = False) -> dict:
    return {
        "text": text or f"第{i}段：本产品保本保收益，年化6.8%。",
        "page": 1,
        "paragraph": i,
        "heading": heading,
    }


def test_disabled_keeps_one_unit_per_block():
    units = mod._scan_units([_b(1), _b(2), _b(3)], 0)
    assert len(units) == 3
    assert units[0]["paragraph"] == 1
    assert len(units[0]["_parts"]) == 1


def test_merges_small_blocks_into_one_unit():
    units = mod._scan_units([_b(1), _b(2), _b(3)], 1200)
    assert len(units) == 1
    assert units[0]["text"].count("保本保收益") == 3
    assert len(units[0]["_parts"]) == 3


def test_splits_when_exceeding_max_chars():
    big = "字" * 600
    units = mod._scan_units([_b(1, big), _b(2, big), _b(3, big)], 1000)
    assert len(units) == 3  # 每段 600 字，两段就超 1000


def test_heading_starts_new_unit():
    units = mod._scan_units([_b(1), _b(2, heading=True), _b(3)], 1200)
    assert len(units) == 2
    assert units[1]["paragraph"] == 2  # 标题段独立起头


def test_relocate_points_back_to_original_paragraph():
    parts = [_b(1), _b(2, "第2段：稳赚不赔，零风险。"), _b(3)]
    finding = {"original_text": "稳赚不赔，零风险", "page": 1, "paragraph": 1}
    out = mod._relocate(finding, parts)
    assert out["paragraph"] == 2


def test_relocate_falls_back_when_text_not_found():
    parts = [_b(1), _b(2)]
    finding = {"original_text": "文档里没有这句话", "page": 1, "paragraph": 1}
    out = mod._relocate(finding, parts)
    assert out["paragraph"] == 1  # 保持单元首段，不丢定位


def test_llm_scan_calls_llm_once_when_merged(monkeypatch):
    """合并开启后：6 个小段只发 1 次 LLM 调用。"""

    class _Fake:
        model = "fake"

        def __init__(self):
            self.calls = 0

        async def achat_json(self, messages, temperature=None, **kwargs):
            self.calls += 1
            text = messages[-1]["content"]
            return (
                [
                    {
                        "type": "禁止性",
                        "issue": "保本承诺",
                        "original_text": text[text.find("保本") : text.find("保本") + 6],
                        "regulation": "某办法 第一条",
                        "reason": "承诺保本",
                        "suggestion": "删除",
                        "severity": "high",
                        "confidence": 0.9,
                    }
                ],
                {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                [],
            )

    fake = _Fake()
    monkeypatch.setattr(mod, "get_llm", lambda: fake)
    cfg = {"llm_scan_chunk_chars": 1200, "llm_concurrency": 1}
    # pydantic 实例不允许覆盖方法，改为给类打补丁（只影响本用例）
    monkeypatch.setattr(
        type(mod.settings),
        "app_config",
        lambda self, sec: cfg if sec == "workflow" else {},
    )

    state = {"blocks": [_b(i) for i in range(1, 7)], "matched_articles": []}
    result = mod.llm_scan(state)
    assert fake.calls == 1
    assert len(result["llm_findings"]) == 1
