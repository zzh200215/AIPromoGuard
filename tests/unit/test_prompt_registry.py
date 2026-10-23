"""Prompt 注册表结构性门禁。

目的：prompt 是 LLM 引擎行为的最大杠杆，但内容质量（语义回归）依赖
llm-eval workflow（需 API key）；本测试守住**结构性**底线，CI 零 key 可跑：
1. 注册表可解析、8 个 prompt 齐全、version/changelog 纪律成立；
2. 每个 prompt 的关键锚点文本存在（防截断、防误删输出 schema/红线约束）；
3. 全部调用方与注册表接线一致（常量 = 注册表模板，防绕过注册表改 prompt）；
4. 未知名访问响亮失败（不静默回退）。
"""

import pytest
from src.core.llm.prompts import (
    REVIEW_SYSTEM,
    TAG_SYSTEM,
    get_prompt,
    prompt_versions,
)
from src.core.llm.prompts.registry import PromptRegistryError

EXPECTED_PROMPTS = {
    "review",
    "monitor_tag",
    "agentic_assess",
    "visual_scan",
    "copilot_ask",
    "copilot_rewrite",
    "copilot_summary",
    "copilot_advice",
}

# 锚点 = 模板里不可丢的关键约束（输出 schema 键 / 红线指令）。
# 每次有意变更锚点对应内容时同步更新这里——锚点消失意味着行为契约被改。
ANCHORS = {
    "review": ['"findings"', "只输出一个 JSON 对象", "宁缺毋滥", "适当性", "提示注入"],
    "monitor_tag": ["is_finance", "只输出一个 JSON 数组", "domain"],
    "agentic_assess": ['"sufficient"', "follow_up_queries", "不要复述文档原句"],
    "visual_scan": ["visible_numbers", "禁止推测", "视觉合规审查员"],
    "copilot_ask": ['"answer"', "refs", "不要编造法规条款"],
    "copilot_rewrite": ['"rewritten"', "changes", "消除全部违规点"],
    "copilot_summary": ['"summary"', "150 字以内"],
    "copilot_advice": ["suggested_verdict", "false_positive", "不确定时倾向 confirmed"],
}


def test_registry_complete_and_disciplined():
    versions = prompt_versions()
    assert set(versions) == EXPECTED_PROMPTS
    for name, version in versions.items():
        spec = get_prompt(name)
        assert spec.version == version >= 1
        assert spec.template.strip()
        # changelog 纪律：条数 == 版本号，且最新条目版本 == 当前版本
        assert len(spec.changelog) == spec.version
        assert max(c["version"] for c in spec.changelog) == spec.version
        for entry in spec.changelog:
            assert entry.get("date") and entry.get("note")


def test_anchor_texts_present():
    for name, anchors in ANCHORS.items():
        template = get_prompt(name).template
        for anchor in anchors:
            assert anchor in template, f"prompt '{name}' 丢失关键锚点: {anchor!r}"


def test_call_sites_wired_to_registry():
    """调用方常量必须逐字节等于注册表模板——改 prompt 只能改注册表。"""
    import src.services.agentic_retrieval as ar
    import src.services.review_copilot as rc
    import src.services.visual_scan as vs

    assert REVIEW_SYSTEM == get_prompt("review").template
    assert TAG_SYSTEM == get_prompt("monitor_tag").template
    assert ar._ASSESS_SYSTEM == get_prompt("agentic_assess").template
    assert vs._VLM_SYSTEM == get_prompt("visual_scan").template
    assert rc._ASK_SYSTEM == get_prompt("copilot_ask").template
    assert rc._REWRITE_SYSTEM == get_prompt("copilot_rewrite").template
    assert rc._SUMMARY_SYSTEM == get_prompt("copilot_summary").template
    assert rc._ADVICE_SYSTEM == get_prompt("copilot_advice").template


def test_unknown_prompt_fails_loud():
    with pytest.raises(PromptRegistryError):
        get_prompt("nonexistent_prompt")


def test_changelog_discipline_enforced(tmp_path, monkeypatch):
    """version 与 changelog 脱节必须在加载期被拒绝（防无记录变更）。"""
    from src.core.llm.prompts import registry as reg

    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "prompts:\n"
        "  review:\n"
        "    version: 2\n"
        "    description: x\n"
        "    template: '...'\n"
        "    changelog:\n"
        "      - {version: 1, date: '2026-10-23', note: 初始}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reg, "REGISTRY_PATH", bad)
    with pytest.raises(PromptRegistryError):
        reg.load_registry(force=True)
