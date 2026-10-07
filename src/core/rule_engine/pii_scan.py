"""内置 PII 敏感信息检测（R1-1，对标 AllocateRite 材料内嵌客户信息场景）.

与 utils/masking 的分工：masking 是**存储脱敏**（不该出现也给你遮住）；
本模块是**审查维度**——营销材料中出现疑似真实客户身份证/手机号/银行卡/
邮箱/微信号本身就是违规（高频事故：真实案例改编海报忘了换联系方式），
设计为"材料不该出现"的一票否决型检查。

设计约束：
- 代码内置、不进 rules 表（不可停用、不受规则版本管理）：身份/联系方式
  泄露是确定性红线，不走 draft→对抗验证的规则生命周期；
- 确定性算法压误报：身份证 GB 11643 校验位、银行卡 Luhn、前后数字边界
  断言（防从长编号中间截出假手机号）、微信号必须有"微信号"类标签前缀；
- rule_id=None：ReviewResult.rule_id 是 BigInteger 列，内置规则无 DB 行，
  身份经 rule_name/description 透出（落库链路 _citation_for_rule 对
  None 直接返回无引用，天然兼容）；
- confidence=1.0：走 rule 路信任分级（高置信自动确认），与"确定性红线"
  定位一致。
"""

from __future__ import annotations

import re

from src.core.rule_engine.engine import RuleHit
from src.parsers.base import TextBlock

# 法规引用（规则路结构化溯源之外的通用文本引用，随 related_regulations 透出）
PII_REGULATIONS = ["《中华人民共和国个人信息保护法》"]

_DESCRIPTIONS = {
    "id_card": "材料包含疑似真实客户身份证号，涉嫌泄露个人敏感信息",
    "phone": "材料包含疑似真实客户手机号，涉嫌泄露个人联系方式",
    "bank_card": "材料包含疑似真实客户银行卡号，涉嫌泄露金融账户信息",
    "email": "材料包含疑似真实客户电子邮箱，涉嫌泄露个人联系方式",
    "wechat": "材料包含微信号引流信息，涉嫌绕开销售适当性管理渠道",
}

_SEVERITY = {
    "id_card": "high",
    "phone": "high",
    "bank_card": "high",
    "email": "medium",
    "wechat": "medium",
}

# 维度身份前缀：results serializer 依据落库 description 头部派生 finding_kind，
# 前缀常量在此单点定义（_NAME 用它构造），文案漂移会被 test_finding_kind_prefixes 拦截
PII_KIND_PREFIX = "敏感信息"

_NAME = {
    "id_card": f"{PII_KIND_PREFIX}：身份证号",
    "phone": f"{PII_KIND_PREFIX}：手机号",
    "bank_card": f"{PII_KIND_PREFIX}：银行卡号",
    "email": f"{PII_KIND_PREFIX}：电子邮箱",
    "wechat": f"{PII_KIND_PREFIX}：微信号",
}

# GB 11643-1999 校验码映射：check = MAP[sum(wi*ai) mod 11]
_ID_MAP = "10X98765432"
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)

_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])"
)
# 微信号必须有显式标签（无标签的字母数字串误报不可控）
_WECHAT = re.compile(
    r"(?:微信号|微信公众号|weixin|wechat|vx|VX|wx|WX)[:：\s]*([A-Za-z][A-Za-z0-9_-]{5,19})"
)


def _id_card_valid(num: str) -> bool:
    """GB 11643-1999 校验位验证（X/x 视为 10）。"""
    if len(num) != 18:
        return False
    total = 0
    for i, ch in enumerate(num[:17]):
        if not ch.isdigit():
            return False
        total += int(ch) * _ID_WEIGHTS[i]
    expected = _ID_MAP[total % 11]
    return num[17].upper() == expected


def _luhn_valid(num: str) -> bool:
    """Luhn 算法（银行卡号校验）。"""
    if not num.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:  # 从右数偶数位（0 起）×2
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _spans(text: str) -> list[tuple[int, int, str]]:
    """返回 (start, end, kind) 列表；同区间只保留最高优先级类型。"""
    found: list[tuple[int, int, str]] = []

    for m in _ID_CARD.finditer(text):
        if _id_card_valid(m.group()):
            found.append((m.start(), m.end(), "id_card"))

    taken = [(s, e) for s, e, _ in found]

    def _overlapsTaken(s: int, e: int) -> bool:
        return any(s < te and ts < e for ts, te in taken)

    for m in _BANK_CARD.finditer(text):
        s, e = m.start(), m.end()
        if _overlapsTaken(s, e):
            continue  # 身份证也满足 13-19 位，已识别为身份证的不再按卡报
        if _luhn_valid(m.group()):
            found.append((s, e, "bank_card"))

    for m in _PHONE.finditer(text):
        found.append((m.start(), m.end(), "phone"))

    for m in _EMAIL.finditer(text):
        found.append((m.start(), m.end(), "email"))

    for m in _WECHAT.finditer(text):
        # 只标账号本身，标签不进 matched_text（报告展示更干净）
        found.append((m.start(1), m.end(1), "wechat"))

    # 同区间去重（保优先级：id_card > bank_card > phone > email > wechat）
    seen: set[tuple[int, int]] = set()
    unique: list[tuple[int, int, str]] = []
    for s, e, kind in found:
        if (s, e) not in seen:
            seen.add((s, e))
            unique.append((s, e, kind))
    return unique


def scan_pii(blocks: list[TextBlock]) -> list[RuleHit]:
    """对文档块执行内置 PII 扫描，产出与规则路同 schema 的 RuleHit。"""
    hits: list[RuleHit] = []
    for block in blocks:
        for s, e, kind in _spans(block.text):
            hits.append(
                RuleHit(
                    rule_id=None,
                    rule_name=_NAME[kind],
                    domain="general",
                    severity=_SEVERITY[kind],
                    rule_type="pii",
                    matched_text=block.text[s:e],
                    char_start=s,
                    char_end=e,
                    page=block.page,
                    paragraph=block.paragraph,
                    confidence=1.0,
                    related_regulations=list(PII_REGULATIONS),
                    description=_DESCRIPTIONS[kind],
                )
            )
    return hits


# 方案 A：脱敏命中元数据 → PII 命中。kind 与 masking 的采集键一致。
_SPAN_KINDS = ("id_card", "bank_card", "phone")


def scan_pii_from_spans(spans: list[dict]) -> list[RuleHit]:
    """从解析脱敏时采集的命中元数据产出 PII 命中（方案 A）。

    背景：解析阶段（PRD §13.2）已先把 PII 脱敏为 `138****5678`，
    之后任何基于原文格式的扫描（scan_pii 的正则）都不可能命中——
    检测数据源因此前移到脱敏那一刻的正则命中记录（每类按数量聚合一条命中）。
    """
    counts: dict[str, int] = {}
    for span in spans:
        kind = span.get("kind")
        if kind in _SPAN_KINDS:
            counts[kind] = counts.get(kind, 0) + 1

    hits: list[RuleHit] = []
    for kind, n in counts.items():
        # 取该类首个 span 的块位置（元数据来自解析层，携带 page/paragraph）
        first = next(s for s in spans if s.get("kind") == kind)
        hits.append(
            RuleHit(
                rule_id=None,
                rule_name=_NAME[kind],
                domain="general",
                severity=_SEVERITY[kind],
                rule_type="pii",
                # 原文片段不落此处（隐私最小化）：只暴露类型与数量
                matched_text=f"[已脱敏] {_NAME[kind]}" + (f" × {n}" if n > 1 else ""),
                char_start=0,  # 脱敏后无原文坐标，位置由 page/paragraph 承载
                char_end=0,
                page=first.get("page"),
                paragraph=first.get("paragraph"),
                confidence=1.0,
                related_regulations=list(PII_REGULATIONS),
                description=_DESCRIPTIONS[kind] + f"（共 {n} 处，原文已脱敏，位置见材料原文）",
            )
        )
    return hits
