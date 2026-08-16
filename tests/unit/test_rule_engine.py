from src.core.rule_engine import RuleScanner
from src.core.rule_engine.matchers.keyword_matcher import KeywordMatcher
from src.core.rule_engine.matchers.regex_matcher import RegexMatcher
from src.parsers.base import TextBlock


class FakeRule:
    def __init__(
        self, rule_name, domain, severity, rule_type, rule_content, description=None, id=1
    ):
        self.id = id
        self.rule_name = rule_name
        self.domain = domain
        self.severity = severity
        self.rule_type = rule_type
        self.rule_content = rule_content
        self.description = description


def test_regex_matcher():
    spans = RegexMatcher().match(
        "预期年化收益率4.5%，历史收益稳定",
        {"type": "regex", "pattern": "预期年化.{0,8}\\d+(\\.\\d+)?%"},
    )
    assert len(spans) == 1
    assert "预期年化收益率4.5%" in spans[0].text


def test_keyword_matcher_any():
    spans = KeywordMatcher().match(
        "本产品保本保收益，零风险",
        {"type": "keyword", "keywords": ["保本", "零风险"], "match_mode": "any"},
    )
    assert len(spans) == 2
    assert all(s.start < s.end for s in spans)


def test_keyword_matcher_all_requires_all_keywords():
    cond = {"type": "keyword", "keywords": ["无风险", "高收益"], "match_mode": "all"}
    assert KeywordMatcher().match("仅有无风险", cond) == []
    assert len(KeywordMatcher().match("无风险高收益产品", cond)) == 2


def test_scanner_composite_or():
    rule = FakeRule(
        rule_name="禁止刚性兑付承诺",
        domain="banking",
        severity="high",
        rule_type="composite",
        rule_content={
            "operator": "OR",
            "conditions": [
                {"type": "regex", "pattern": "保本保息|保本保收益"},
                {
                    "type": "keyword",
                    "keywords": ["刚性兑付"],
                    "match_mode": "any",
                    "context_window": 10,
                },
            ],
            "related_regulations": ["《资管新规》第十九条"],
        },
    )
    hits = RuleScanner().scan(
        [TextBlock(text="本产品保本保息，预期年化5%", page=2, paragraph=3)], [rule]
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit.page == 2 and hit.paragraph == 3
    assert hit.severity == "high"
    assert "保本保息" in hit.matched_text
    assert hit.confidence == 0.95


def test_scanner_and_requires_all_conditions():
    rule = FakeRule(
        rule_name="无风险高收益组合",
        domain="banking",
        severity="high",
        rule_type="keyword",
        rule_content={
            "operator": "AND",
            "conditions": [
                {
                    "type": "keyword",
                    "keywords": ["无风险"],
                    "match_mode": "any",
                    "context_window": 10,
                },
                {
                    "type": "keyword",
                    "keywords": ["高收益"],
                    "match_mode": "any",
                    "context_window": 10,
                },
            ],
        },
    )
    scanner = RuleScanner()
    assert scanner.scan([TextBlock(text="本产品无风险", page=1, paragraph=1)], [rule]) == []
    assert len(scanner.scan([TextBlock(text="无风险高收益", page=1, paragraph=1)], [rule])) == 2


def test_scanner_filters_by_domain():
    banking_rule = FakeRule(
        rule_name="保本规则",
        domain="banking",
        severity="high",
        rule_type="keyword",
        rule_content={
            "operator": "OR",
            "conditions": [{"type": "keyword", "keywords": ["保本"], "match_mode": "any"}],
        },
    )
    fund_rule = FakeRule(
        rule_name="基金规则",
        domain="fund",
        severity="high",
        rule_type="keyword",
        rule_content={
            "operator": "OR",
            "conditions": [{"type": "keyword", "keywords": ["保本"], "match_mode": "any"}],
        },
    )
    text = [TextBlock(text="保本产品", page=1, paragraph=1)]
    scanner = RuleScanner()
    assert len(scanner.scan(text, [banking_rule, fund_rule])) == 2
    assert len(scanner.scan(text, [banking_rule, fund_rule], domain="banking")) == 1
    assert len(scanner.scan(text, [banking_rule, fund_rule], domain="fund")) == 1


def test_scanner_dedupes_same_span_from_multiple_conditions():
    rule = FakeRule(
        rule_name="保本类关键词",
        domain="banking",
        severity="medium",
        rule_type="composite",
        rule_content={
            "operator": "OR",
            "conditions": [
                {"type": "regex", "pattern": "保本"},
                {"type": "keyword", "keywords": ["保本"], "match_mode": "any", "context_window": 5}
            ],
        },
    )
    hits = RuleScanner().scan([TextBlock(text="承诺保本", page=1, paragraph=1)], [rule])
    assert len(hits) == 1


# ---- 否定表述抑制（评估暴露的误报：营销文案合规表述"不保本不保收益"被误触发）----

def test_keyword_matcher_suppresses_negation():
    m = KeywordMatcher()
    cond = {"type": "keyword", "keywords": ["保本", "保收益"], "match_mode": "any"}
    assert m.match("本产品不保本不保收益", cond) == []   # 否定语境全抑制
    assert len(m.match("本产品保本保收益", cond)) == 2    # 肯定表述正常命中


def test_keyword_matcher_negation_inside_keyword_not_suppressed():
    # "无风险" 的"无"是关键词自身的一部分，不是命中位置之前的否定
    spans = KeywordMatcher().match(
        "本产品无风险", {"type": "keyword", "keywords": ["无风险"], "match_mode": "any"}
    )
    assert len(spans) == 1


def test_regex_matcher_suppresses_negation():
    m = RegexMatcher()
    cond = {"type": "regex", "pattern": "返还本金|本金返还"}
    assert m.match("本产品不返还本金", cond) == []
    assert len(m.match("本产品返还本金", cond)) == 1


def test_negation_window_zero_disables_suppression():
    m = KeywordMatcher()
    cond = {"type": "keyword", "keywords": ["保本"], "match_mode": "any", "negation_window": 0}
    assert len(m.match("本产品不保本", cond)) == 1        # 关闭否定抑制后恢复命中


def test_negation_window_catches_indirect_negation():
    # "不承诺保本"：否定词"不"隔了"承诺"，同从句内应抑制
    m = KeywordMatcher()
    cond = {"type": "keyword", "keywords": ["保本"], "match_mode": "any"}
    assert m.match("本产品不承诺保本", cond) == []


def test_negation_does_not_leak_across_keywords():
    # "无风险"的"无"不能否定后随的"高收益"（"无风险高收益"是真实违规，不能误抑制）
    spans = KeywordMatcher().match(
        "无风险高收益产品",
        {"type": "keyword", "keywords": ["无风险", "高收益"], "match_mode": "any"},
    )
    assert len(spans) == 2

def test_negation_covers_long_verb_phrase():
    # "不承诺保本保收益"：否定作用于整个动词短语，尾部关键词"保收益"（距"不"5 字符）也应抑制
    m = KeywordMatcher()
    cond = {"type": "keyword", "keywords": ["保本", "保收益"], "match_mode": "any"}
    assert m.match("产品不承诺保本保收益", cond) == []


def test_negation_does_not_cross_clause():
    # 否定词不跨标点分隔的从句生效
    m = KeywordMatcher()
    cond = {"type": "keyword", "keywords": ["保本"], "match_mode": "any"}
    assert len(m.match("本产品不保本，保本收益另计", cond)) == 1
