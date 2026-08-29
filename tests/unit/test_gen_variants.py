"""对抗评估集生成器的纯逻辑单测（离线：mock LLM、不连库）。

覆盖 scripts/evaluate/gen_variants.py 的：
- 样本指纹（去重键）
- LLM 样本生成的结构校验（变体数不足/JSON 坏/缺合规反例 → None）
- 规则 DSL → 生成提示词的模式描述
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

_EVAL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evaluate" / "gen_variants.py"
_spec = importlib.util.spec_from_file_location("gen_variants", _EVAL_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _rule(**overrides):
    base = SimpleNamespace(
        id=7,
        domain="banking",
        rule_name="禁止保本保收益表述",
        rule_type="regex",
        rule_content={"operator": "OR", "conditions": [
            {"type": "regex", "pattern": "保本保收益|稳赚不赔"}
        ]},
        severity="high",
        description="依据：《测试办法》第一条",
        is_active=1,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_fingerprint_differs_by_text():
    a = {"text": "本产品保本保收益"}
    b = {"text": "本产品不保本"}
    assert mod._fingerprint(a) != mod._fingerprint(b)
    assert mod._fingerprint(a) == mod._fingerprint(dict(a))
    assert len(mod._fingerprint(a)) == 16


def test_rule_pattern_text_describes_dsl():
    rule = _rule()
    text = mod._rule_pattern_text(rule)
    assert "保本保收益" in text and "正则" in text
    rule2 = _rule(rule_content={"operator": "OR", "conditions": [
        {"type": "keyword", "keywords": ["稳赚", "零风险"]}
    ]})
    text2 = mod._rule_pattern_text(rule2)
    assert "稳赚" in text2 and "关键词" in text2


def _llm_returning(payload):
    return SimpleNamespace(chat=lambda messages: payload)


def test_generate_for_rule_builds_case():
    payload = json.dumps(
        {
            "variants": ["本产品保本保收益，年化可达8%", "稳赚不赔，随时可退"],
            "compliant": "本产品不保本，投资需谨慎。",
        },
        ensure_ascii=False,
    )
    case = mod.generate_for_rule(_llm_returning(payload), _rule())
    assert case is not None
    assert case["id"] == "mined-7-banking"
    assert case["domain"] == "banking"
    assert len(case["ground_truth"]) == 2
    assert case["ground_truth"][0]["rule_name"] == "禁止保本保收益表述"
    assert case["ground_truth"][0]["risk_level"] == "high"
    assert case["negative_ground_truth"] == [{"text": "本产品不保本，投资需谨慎。"}]


def test_generate_for_rule_rejects_bad_output():
    assert mod.generate_for_rule(_llm_returning("不是 JSON"), _rule()) is None
    # 变体数不足 2 → 拒绝
    few = json.dumps({"variants": ["只有一条"], "compliant": "合规句"}, ensure_ascii=False)
    assert mod.generate_for_rule(_llm_returning(few), _rule()) is None
    # 缺合规反例 → 拒绝
    no_neg = json.dumps({"variants": ["甲", "乙"]}, ensure_ascii=False)
    assert mod.generate_for_rule(_llm_returning(no_neg), _rule()) is None


def test_generate_for_rule_normalizes_severity():
    payload = json.dumps(
        {"variants": ["甲话术保本保收益", "乙话术稳赚不赔"], "compliant": "本产品不保本。"},
        ensure_ascii=False,
    )
    case = mod.generate_for_rule(_llm_returning(payload), _rule(severity="critical"))
    assert case["ground_truth"][0]["risk_level"] == "medium"  # 非法档位回退
