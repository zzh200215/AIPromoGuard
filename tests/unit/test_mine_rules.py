"""规则挖掘管道的解析与预校验单测（离线：不调 LLM、不连库）。

覆盖 scripts/crawl/mine_rules_from_regulations.py 的：
- 候选解析：regex 预编译拦截、缺少正例拒绝、非法域回退
- 引擎冒烟测试：正例必须命中 / 否定变体与合规语料必须不命中
- 字面量提取与语义重叠查重
"""

import importlib.util
from pathlib import Path

_EVAL_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "crawl" / "mine_rules_from_regulations.py"
)
_spec = importlib.util.spec_from_file_location("mine_rules", _EVAL_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _candidate(**overrides) -> dict:
    base = {
        "domain": "banking",
        "rule_name": "禁止保本保收益表述",
        "rule_type": "regex",
        "rule_content": {"operator": "OR", "conditions": [
            {"type": "regex", "pattern": "保本保收益|稳赚不赔"}
        ]},
        "severity": "high",
        "description": "依据：《测试办法》第一条",
        "examples_hit": ["本产品保本保收益，收益可观"],
    }
    base.update(overrides)
    return base


def test_parse_candidates_rejects_invalid_regex():
    raw = '[{"rule_name": "坏正则", "rule_type": "regex", "pattern": "保本(((", ' \
          '"severity": "high", "examples_hit": ["保本"], "domain": "banking"}]'
    assert mod.parse_candidates(raw) == []


def test_parse_candidates_requires_examples():
    raw = '[{"rule_name": "无正例", "rule_type": "regex", "pattern": "保本", "domain": "banking"}]'
    assert mod.parse_candidates(raw) == []


def test_parse_candidates_accepts_keyword_and_fallback_domain():
    raw = (
        '[{"rule_name": "禁止夸大表述", "rule_type": "keyword", "keywords": ["稳赚", "零风险"],'
        '"severity": "medium", "examples_hit": ["本产品稳赚不亏"], "domain": "crypto"}]'
    )
    cands = mod.parse_candidates(raw)
    assert len(cands) == 1
    assert cands[0]["domain"] is None  # 非法域交由调用方按法规域回退
    assert cands[0]["rule_content"]["conditions"][0]["type"] == "keyword"


def test_smoke_test_passes_for_precise_rule():
    ok, reason = mod.smoke_test(_candidate())
    assert ok, reason


def test_smoke_test_rejects_negation_violation():
    # 关闭否定语境抑制（negation_window=0）后，"本产品不保本"这类合规声明会被命中
    cand = _candidate(rule_content={"operator": "OR", "conditions": [
        {"type": "keyword", "keywords": ["保本"], "match_mode": "any",
         "context_window": 15, "negation_window": 0}
    ]})
    ok, reason = mod.smoke_test(cand)
    assert not ok
    # 抑制关闭后合规语料/否定变体必有一处误命中
    assert "误命中" in reason


def test_smoke_test_rejects_overbroad_keyword():
    # "过往业绩"在合规声明（"过往业绩不预示未来表现"）中无否定前缀 → 语料误命中 → 拒绝
    cand = _candidate(rule_name="禁止提及过往业绩", rule_content={"operator": "OR", "conditions": [
        {"type": "keyword", "keywords": ["过往业绩"], "match_mode": "any", "context_window": 15}
    ]})
    ok, reason = mod.smoke_test(cand)
    assert not ok
    assert "合规语料" in reason


def test_smoke_test_rejects_when_positive_misses():
    cand = _candidate(rule_content={"operator": "OR", "conditions": [
        {"type": "regex", "pattern": "本金无忧"}
    ]})
    ok, reason = mod.smoke_test(cand)  # 正例"保本保收益"不命中该正则
    assert not ok
    assert "正例未命中" in reason


def test_semantic_dedup():
    seen = [{"保本保收益", "稳赚不赔"}]
    dup = _candidate(rule_content={"operator": "OR", "conditions": [
        {"type": "regex", "pattern": "稳赚不赔|保本保收益"}
    ]})
    assert mod._semantically_duplicate(dup, seen)
    fresh = _candidate(rule_content={"operator": "OR", "conditions": [
        {"type": "regex", "pattern": "保单利益确定|结算利率保证"}
    ]})
    assert not mod._semantically_duplicate(fresh, seen)


def test_compliant_corpus_covers_all_domains():
    assert set(mod._COMPLIANT_CORPUS) == {"banking", "fund", "insurance"}
    for _domain, sentences in mod._COMPLIANT_CORPUS.items():
        assert len(sentences) >= 5
        assert all(s.strip() for s in sentences)
