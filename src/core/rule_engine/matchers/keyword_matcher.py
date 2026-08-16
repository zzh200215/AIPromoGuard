"""关键词 matcher：condition = {
    "type": "keyword",
    "keywords": [...],
    "match_mode": "any" | "all",      # any 默认
    "context_window": 20,             # 命中前后各截取字符数作为证据片段
}。"""

import re

from src.core.rule_engine.matchers.base import Matcher, MatchSpan


class KeywordMatcher(Matcher):
    name = "keyword"
    confidence = 0.85

    def match(self, text: str, condition: dict) -> list[MatchSpan]:
        keywords = condition.get("keywords") or []
        mode = condition.get("match_mode", "any")
        window = condition.get("context_window", 20)

        if mode == "all":
            missing = [k for k in keywords if k not in text]
            if missing:
                return []

        spans: list[MatchSpan] = []
        for keyword in keywords:
            for m in re.finditer(re.escape(keyword), text):
                start = max(0, m.start() - window)
                end = min(len(text), m.end() + window)
                # start/end 存关键词本身的字符位置（与 regex matcher 语义一致，用于去重）；
                # text 为加窗后的证据片段，供报告溯源展示。
                spans.append(MatchSpan(text=text[start:end], start=m.start(), end=m.end()))
        return self._filter_negated(spans, text, condition)
