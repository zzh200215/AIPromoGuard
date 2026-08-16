"""敏感信息脱敏（PRD §13.2）：身份证号 / 手机号 / 银行卡号 / 金额。

在解析阶段完成后应用，系统后续处理的是脱敏后文本。
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


def mask_sensitive(text: str) -> str:
    """对文本中的身份证/手机号/银行卡/金额做脱敏。"""
    text = _ID_CARD.sub(_mask_id, text)
    text = _BANK_CARD.sub(_mask_bank, text)
    text = _PHONE.sub(_mask_phone, text)
    text = _AMOUNT.sub(_mask_amount, text)
    return text
