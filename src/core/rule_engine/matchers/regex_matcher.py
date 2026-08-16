"""正则 matcher：condition = {"type": "regex", "pattern": "..."}。"""

import re

from src.core.rule_engine.matchers.base import Matcher, MatchSpan


class RegexMatcher(Matcher):
    name = "regex"
    confidence = 0.95

    def match(self, text: str, condition: dict) -> list[MatchSpan]:
        pattern = condition["pattern"]
        try:
            compiled = re.compile(pattern)
        except re.error:
            return []
        spans = [
            MatchSpan(text=m.group(), start=m.start(), end=m.end())
            for m in compiled.finditer(text)
        ]
        return self._filter_negated(spans, text, condition)
