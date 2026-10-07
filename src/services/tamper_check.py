"""VLM×OCR 交叉篡改检测（R2-3，spike 条件通过后落地）.

洞察：图片被局部 P 图（改收益率/期限数字）是真实黑产手法。VLM 看图读数
（spike 验证：关键数字检出 100%、零幻觉），文字材料 blocks 来自 OCR/文档
解析——两者对**同一材料**读出的关键数字应一致；不一致 = 图片被局部修改
或图文不同步（海报与配套说明书各自版本）。

设计约束（来自 spike 结论）：
- 只比对**关键数字**（利率/金额/期限/日期，context 关键词过滤）：spike 中
  全口径检出 89.7% 的漏检全是嵌名词单字数字（理财1号/R3级），不在威胁
  模型内，不参与比对（避免把 VLM 漏读当不一致）；
- 归一化后精确相等才判一致：千分位/全半角/百分号/尾零归一，消灭格式噪声；
  剩余不一致一律报"疑似"（severity=high、confidence=0.7、人工核验）——
  OCR 漏读小字数字是残余误报源，用人工核验兜底而非静默放过；
- 纯函数零 DB：输入 vlm 数字清单 + 全文块，输出与 vlm findings 同 schema
  的 findings，直接并入 vlm_findings 流（source=vlm，永不自动确认）。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# 关键数字的 context 关键词（利率/收益/金额/期限/日期类）
_KEY_CONTEXT_RE = re.compile(
    r"率|收益|金额|利息|费|元|万|亿|天|日|月|年|期|额度|基准|涨幅|规模|下限|上限|起点|门槛"
)

# 千分位优先于普通数字（"50,000" 整体匹配，不拆成 "50"+"000"）
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

_FULLWIDTH = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")

# 维度身份前缀（与 pii_scan.PII_KIND_PREFIX 同模式，见其注释）；
# 落库经 conflict_resolve 的 rule_name=issue 通道写入 description 头部
TAMPER_KIND_PREFIX = "疑似篡改"


def norm_number(raw: str) -> str:
    """数字归一：全角→半角、去千分位/百分号/货币符号、尾零归一。

    3,850.00 → 3850；9.85% → 9.85；３．８５ → 3.85。
    """
    s = (raw or "").translate(_FULLWIDTH)
    s = re.sub(r"[,%￥$€£\s]", "", s)
    s = s.rstrip(".")
    try:
        d = Decimal(s).normalize()
        # normalize 会把整数产出科学计数法（3.85E+3），format 'f' 还原
        return format(d, "f")
    except (InvalidOperation, ValueError):
        return s.strip()


def _is_key_number(context: str, value: str) -> bool:
    """关键数字过滤：context 命中关键词，或数值形态本身是率/大额。"""
    if _KEY_CONTEXT_RE.search(context or ""):
        return True
    # 无 context 时退化为形态判断：含百分号语义的短小数或 ≥4 位金额
    return "." in value or len(re.sub(r"\D", "", value)) >= 4


def extract_text_numbers(blocks: list[dict]) -> set[str]:
    """全文数字集合（归一后）。blocks 为 state["blocks"] 的 dict 形态。"""
    nums: set[str] = set()
    for b in blocks:
        text = b.get("text", "") if isinstance(b, dict) else str(b)
        for raw in NUM_RE.findall(text or ""):
            nums.add(norm_number(raw))
    return nums


def check_tamper(
    vlm_numbers: list[dict], blocks: list[dict], page: int | None = 1
) -> list[dict]:
    """交叉校验：VLM 读出的关键数字 vs 文字材料数字集。

    vlm_numbers: [{"value": "9.85", "context": "年化收益率"}, ...]（来自
    visual_scan 的 visible_numbers 输出）。
    返回与 vlm findings 同 schema 的 findings 列表（可疑才产出）。
    """
    if not vlm_numbers or not blocks:
        return []
    text_nums = extract_text_numbers(blocks)

    findings: list[dict] = []
    for item in vlm_numbers:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        context = str(item.get("context") or "").strip()
        if not value or not _is_key_number(context, value):
            continue
        if norm_number(value) in text_nums:
            continue
        findings.append(
            {
                "issue": f"{TAMPER_KIND_PREFIX}：图片数字与文字材料不一致",
                "reason": (
                    f"图片中读到数字 {value}（{context or '关键数字'}），"
                    "但文字材料全文未出现该数字——图片可能被局部修改或与配套文字不同步"
                ),
                "original_text": f"{context} {value}".strip(),
                "severity": "high",
                "confidence": 0.7,
                "suggestion": "人工核对原图：确认是否被 P 图修改数字，或图片与文字材料版本不同步",
                "page": page,
            }
        )
    return findings
