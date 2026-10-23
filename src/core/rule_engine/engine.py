"""规则扫描引擎：对文档块执行规则 DSL（regex/keyword/composite）。

执行逻辑（PRD §5.4.3）：
1. 按领域过滤 active 规则（由调用方提供 rules 列表）；
2. 对每条规则、每个文档块执行匹配；
3. 记录匹配位置（字符起止 + page/paragraph）、原文片段、规则 ID；
4. 输出结构化命中结果 RuleHit。
"""

from dataclasses import dataclass, field

from src.core.rule_engine.matchers import Matcher, MatchSpan
from src.core.rule_engine.matchers.keyword_matcher import KeywordMatcher
from src.core.rule_engine.matchers.regex_matcher import RegexMatcher
from src.parsers.base import TextBlock


@dataclass
class RuleHit:
    rule_id: int | str
    rule_name: str
    domain: str
    severity: str
    rule_type: str
    matched_text: str
    char_start: int
    char_end: int
    page: int | None
    paragraph: int | None
    confidence: float
    related_regulations: list[str] = field(default_factory=list)
    description: str | None = None


class RuleScanner:
    def __init__(self) -> None:
        self._matchers: dict[str, Matcher] = {
            RegexMatcher.name: RegexMatcher(),
            KeywordMatcher.name: KeywordMatcher(),
        }

    def scan(
        self,
        blocks: list[TextBlock],
        rules: list,
        domain: str | None = None,
    ) -> list[RuleHit]:
        """按领域过滤 active 规则后扫描文档块。

        domain 为 None 时不过滤（用于跨领域或分类未定的场景）；
        domain 为 "general" 的规则是全局规则（如提示注入防护），对任意领域生效。
        """
        if domain:
            rules = [
                r for r in rules
                if getattr(r, "domain", None) in (domain, "general")
            ]
        hits: list[RuleHit] = []
        for block in blocks:
            for rule in rules:
                rule_content = rule.rule_content or {}
                for span in self._evaluate(rule_content, block.text):
                    hits.append(self._build_hit(rule, block, span))
        return hits

    def _evaluate(self, rule_content: dict, text: str) -> list[MatchSpan]:
        conditions = rule_content.get("conditions") or []
        operator = str(rule_content.get("operator", "OR")).upper()

        evaluated: list[list[MatchSpan]] = []
        for cond in conditions:
            matcher = self._matchers.get(cond.get("type"))
            if matcher is None:
                continue
            evaluated.append(matcher.match(text, cond))

        if operator == "AND":
            if any(not spans for spans in evaluated):
                return []
            spans = [s for group in evaluated for s in group]
        else:  # OR
            spans = [s for group in evaluated for s in group]

        return self._dedupe(spans)

    @staticmethod
    def _dedupe(spans: list[MatchSpan]) -> list[MatchSpan]:
        seen: set[tuple[int, int]] = set()
        result: list[MatchSpan] = []
        for s in spans:
            key = (s.start, s.end)
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result

    def _build_hit(self, rule, block: TextBlock, span: MatchSpan) -> RuleHit:
        rule_content = rule.rule_content or {}
        confidence = self._confidence(rule_content)
        return RuleHit(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            domain=rule.domain,
            severity=rule.severity,
            rule_type=rule.rule_type,
            matched_text=span.text,
            char_start=span.start,
            char_end=span.end,
            page=block.page,
            paragraph=block.paragraph,
            confidence=confidence,
            related_regulations=list(rule_content.get("related_regulations") or []),
            description=rule.description,
        )

    def _confidence(self, rule_content: dict) -> float:
        conditions = rule_content.get("conditions") or []
        return max(
            (
                self._matchers[cond["type"]].confidence
                for cond in conditions
                if cond.get("type") in self._matchers
            ),
            default=0.5,
        )


rule_scanner = RuleScanner()
