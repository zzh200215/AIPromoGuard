"""敏感信息脱敏（PRD §13.2）：身份证号 / 手机号 / 银行卡号 / 金额。

在解析阶段完成后应用，系统后续处理的是脱敏后文本。

**方案 A（2026-10-06）**：脱敏与检测本是一遍扫描的两面——脱敏时正则已经找出了
每个敏感 span，顺手把命中元数据交给下游检测层（`mask_sensitive_with_spans`），
避免"脱敏后文本再也扫不出 PII"的管线缺陷（`scan_pii` 的正则只认原始格式）。
"""

import re

# 身份证：18 位（17 数字 + 数字/X），保留前 3 后 4
_ID_CARD = re.compile(r"\d{17}[\dXx]")
# 手机号：1[3-9] + 9 位，保留前 3 后 4
_PHONE = re.compile(r"1[3-9]\d{9}")
# 银行卡：16-19 位数字，保留后 4
_BANK_CARD = re.compile(r"\d{16,19}")
# 金额：数字（可带小数）+ 单位（万/亿）+ 元，保留量级、数字替换
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*([万亿]?元)")


def _mask_id(match: re.Match) -> str:
    s = match.group()
    return f"{s[:3]}****{s[-4:]}"


def _mask_phone(match: re.Match) -> str:
    s = match.group()
    return f"{s[:3]}****{s[-4:]}"


def _mask_bank(match: re.Match) -> str:
    return f"****{match.group()[-4:]}"


def _mask_amount(match: re.Match) -> str:
    return f"***{match.group(2)}"


# 脱敏顺序与命中采集共用（身份证先于银行卡：18 位身份证也满足 16-19 位数字）
_KIND_MASKERS = (
    ("id_card", _ID_CARD, _mask_id),
    ("bank_card", _BANK_CARD, _mask_bank),
    ("phone", _PHONE, _mask_phone),
    ("amount", _AMOUNT, _mask_amount),
)


def mask_sensitive(text: str) -> str:
    """对文本中的身份证/手机号/银行卡/金额做脱敏。"""
    text = _ID_CARD.sub(_mask_id, text)
    text = _BANK_CARD.sub(_mask_bank, text)
    text = _PHONE.sub(_mask_phone, text)
    text = _AMOUNT.sub(_mask_amount, text)
    return text


def mask_sensitive_with_spans(text: str) -> tuple[str, list[dict]]:
    """脱敏并返回命中元数据（方案 A：脱敏时记录、检测层消费）。

    返回 (脱敏文本, spans)，spans 形如：
        [{"kind": "phone", "value": None},
         {"kind": "amount", "value": "50000"}]

    - PII（身份证/手机号/银行卡）：**只记存在与类型，不带任何原文**
      （隐私最小化——检测层只需知道"有"）；
    - amount：带原数字值（金额是材料自身的宣传数字，非客户隐私；
      且勾稽/数字比对需要值才能计算）。
    """
    spans: list[dict] = []
    for kind, pattern, masker in _KIND_MASKERS:

        def _collect(m: re.Match, kind: str = kind, masker=masker) -> str:
            spans.append(
                {"kind": kind, "value": m.group(1) if kind == "amount" else None}
            )
            return masker(m)

        text = pattern.sub(_collect, text)
    return text, spans
