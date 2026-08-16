"""规则引擎 matcher 基类：单个 condition 的匹配结果与抽象接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

# 中文否定词抑制（修复评估暴露的误报：营销合规表述"不保本不保收益"被规则误触发）。
# 分两类：
#   可靠否定词（窗口内出现即视为否定语境）：不/未/非/别/勿/莫/无法/不能/不得等
#   有歧义否定字（仅紧邻命中前才生效）：无/没 —— "无风险高收益"中的"无"不能否定"高收益"，
#       但"无保底/无保本"是真实否定，故仅紧邻命中时视为否定。
_NEGATION_TERMS = (
    "不", "未", "非", "别", "勿", "莫", "没有", "无法", "不能",
    "不得", "不会", "并非", "不代表", "不构成",
)
_NEGATION_ADJACENT = ("无", "没")
_DEFAULT_NEGATION_WINDOW = 8
# 从句分隔符：否定词不跨从句生效（"本产品不保本，但收益有保障"里"收益"不受"不"影响）
_PUNCT = set("，。；、：！？…—,.;:!?()（） \t\n")


@dataclass
class MatchSpan:
    text: str
    start: int
    end: int


def _is_negated(text: str, start: int, window: int = _DEFAULT_NEGATION_WINDOW) -> bool:
    """命中位置前是否构成否定语境（如"不承诺保本保收益"→"保收益"被否定）。

    - 向前最多看 window 个字符，且不跨标点分隔的从句；
    - 可靠否定词（不/未/非/无法/不能/不得等）在窗口内出现即否定；
    - 有歧义的"无/没"仅紧邻命中前才否定（避免"无风险高收益"里"高收益"被"无"误伤）。
    keyword 自身带否定字（"无风险""稳赚不赔"）不受影响，因为检查的是 start 之前的字符。
    """
    if window <= 0:
        return False
    lo = max(0, start - window)
    for i in range(start - 1, lo - 1, -1):
        if text[i] in _PUNCT:
            lo = i + 1
            break
    prefix = text[lo:start]
    if any(t in prefix for t in _NEGATION_TERMS):
        return True
    return start > 0 and text[start - 1] in _NEGATION_ADJACENT


class Matcher(ABC):
    """对一个 condition（regex/keyword）在文本上执行匹配。"""

    name: str = "base"
    confidence: float = 0.9

    @abstractmethod
    def match(self, text: str, condition: dict) -> list[MatchSpan]:
        """返回全部命中的 span（可重叠，由引擎去重）。"""

    def _filter_negated(
        self, spans: list[MatchSpan], text: str, condition: dict
    ) -> list[MatchSpan]:
        """按 condition.negation_window（默认 3，0 关闭）过滤否定语境命中。"""
        window = condition.get("negation_window", _DEFAULT_NEGATION_WINDOW)
        if window == 0:
            return spans
        return [s for s in spans if not _is_negated(text, s.start, window)]
