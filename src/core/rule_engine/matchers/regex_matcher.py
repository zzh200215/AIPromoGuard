"""正则 matcher：condition = {"type": "regex", "pattern": "..."}。"""

import re
import unicodedata

from src.core.rule_engine.matchers.base import Matcher, MatchSpan


def _normalize_compat(text: str) -> str:
    """逐字符 NFKC：全角数字/字母/百分号（１００％→100%）归一半角后再匹配。

    逐字符处理且多字符展开（如 ﬁ→fi）保持原字符，保证归一化结果与原文
    等长——MatchSpan 的 start/end 偏移在原文上依然有效。
    """
    chars: list[str] = []
    for ch in text:
        nfkc = unicodedata.normalize("NFKC", ch)
        chars.append(nfkc if len(nfkc) == 1 else ch)
    return "".join(chars)


class RegexMatcher(Matcher):
    name = "regex"
    confidence = 0.95

    def match(self, text: str, condition: dict) -> list[MatchSpan]:
        pattern = condition["pattern"]
        try:
            compiled = re.compile(pattern)
        except re.error:
            return []
        normalized = _normalize_compat(text)
        spans = [
            MatchSpan(text=m.group(), start=m.start(), end=m.end())
            for m in compiled.finditer(normalized)
        ]
        return self._filter_negated(spans, normalized, condition)
