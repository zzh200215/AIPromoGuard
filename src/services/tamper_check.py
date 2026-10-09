"""VLM×OCR 交叉篡改检测（R2-3；PR-6 三分支降级分流）.

洞察：图片被局部 P 图（改收益率/期限数字）是真实黑产手法。VLM 看图读数
（spike 验证：关键数字检出 100%、零幻觉），文字材料 blocks 来自 OCR/文档
解析——两者对**同一材料**读出的关键数字应一致；不一致 = 图片被局部修改
或图文不同步（海报与配套说明书各自版本）。

设计约束（来自 spike 结论）：
- 只比对**关键数字**（利率/金额/期限/日期，context 关键词过滤）：spike 中
  全口径检出 89.7% 的漏检全是嵌名词单字数字（理财1号/R3级），不在威胁
  模型内，不参与比对（避免把 VLM 漏读当不一致）；
- 归一化后精确相等才判一致：千分位/全半角/百分号/尾零归一，消灭格式噪声。

PR-6 三分支（原来"集合无 → 一票 changed"是误报主源：OCR 漏读小字数字会被
当成"数字被改"报 high，复核队列被假篡改灌满）：

1. `文字集有且相等` → 一致，无 finding；
2. `同位置有但不等`（context 锚点在文字材料中命中、锚点邻域存在数字，且与
   VLM 值不同）→ **一票 changed**（severity=high、confidence=0.7，与旧口径
   一致）——这是真篡改的形态，检出率红线不允许降；
3. `文字集无此数字`（锚点未命中或邻域没有数字）→ **降级 unverified**
   （severity=medium、confidence=0.45、"待人工核验"）——最可能是 OCR 漏读
   小字数字，也可能是篡改，交人工核对原图，不再冒充确定性结论。

降级只影响分支 3，分支 2 的逻辑完全可分离（见 tests/unit/test_tamper_check.py
三条分支各 ≥3 例 + 真篡改检出率回归）。
聚合护栏：单文档 unverified 占比 >50%（且 ≥3 条）时合并为一条"整档核对"
条目，避免 OCR 系统性漏读把复核队列逐条轰炸。
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

# 锚点邻域半径（字符）：context 命中位置两侧各取 N 字找"对应位置"的数字
_ANCHOR_WINDOW = 32

# 聚合阈值：unverified 条数 ≥ 3 且占全部关键数字比例 > 50% 时合并为整档条目
_AGG_MIN = 3
_AGG_RATIO = 0.5


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


def is_key_number(context: str, value: str) -> bool:
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


def extract_text(blocks: list[dict]) -> str:
    """blocks → 全文文本（锚点定位用；分隔符保留以免跨块误邻接）。"""
    parts = []
    for b in blocks:
        parts.append(b.get("text", "") if isinstance(b, dict) else str(b))
    return "\n".join(parts or [])


def _clean_context(context: str) -> str:
    """context 去噪：去空白与标点，保留实义字符（中英文数字）。"""
    return re.sub(r"[\s\u3000()（）\[\]【】{}:：,，.。;；、/\\|—\-_*\"'“”‘’]+", "", context or "")


def _context_anchors(context: str) -> list[str]:
    """context → 锚点词列表（完整串优先，长串追加 3 字滑窗）。

    完整 context 命中最稳；对"最低认购金额（元）"这类带后缀/括号变体，
    3 字滑窗（如"认购金"）提高与正文措辞的碰撞率。短锚点（<2 字）不可用。
    """
    ctx = _clean_context(context)
    if len(ctx) < 2:
        return []
    anchors = [ctx]
    if len(ctx) > 4:
        anchors += [ctx[i : i + 3] for i in range(len(ctx) - 2)]
    deduped: list[str] = []
    for a in anchors:
        if a not in deduped:
            deduped.append(a)
    return deduped


def _locate_anchor_numbers(text: str, context: str) -> list[tuple[str, str]]:
    """在文本中定位 context 锚点，返回锚点邻域数字 [(归一值, 原文), ...]。

    多锚点/多命中时按"数字到锚点的字符距离"升序去重（同归一值保留最近一次），
    供分支 2 报告"文字材料同位置为 X"。没有任何命中时返回 []（→ 分支 3）。
    """
    anchors = _context_anchors(context)
    if not anchors or not text:
        return []
    best: dict[str, tuple[int, str]] = {}
    for anchor in anchors:
        for m in re.finditer(re.escape(anchor), text):
            lo = max(0, m.start() - _ANCHOR_WINDOW)
            hi = min(len(text), m.end() + _ANCHOR_WINDOW)
            window = text[lo:hi]
            for nm in NUM_RE.finditer(window):
                num_start = lo + nm.start()
                num_end = lo + nm.end()
                # 与锚点区间的字符距离（重叠记 0）
                dist = max(0, m.start() - num_end, num_start - m.end())
                val = norm_number(nm.group())
                if val not in best or dist < best[val][0]:
                    best[val] = (dist, nm.group())
    ordered = sorted(best.items(), key=lambda kv: kv[1][0])
    return [(val, raw) for val, (_, raw) in ordered]


def _changed_finding(value: str, context: str, near_raw: str, page: int | None) -> dict:
    """分支 2：同位置数字不一致（真篡改形态，维持既有判定强度）。"""
    label = context or "关键数字"
    return {
        "issue": f"{TAMPER_KIND_PREFIX}：图片数字与文字材料不一致",
        "reason": (
            f"图片中读到数字 {value}（{label}），文字材料同位置为 {near_raw}——"
            "同位置数字不一致，疑似图片被局部修改"
        ),
        "original_text": f"{label} 图片：{value} ｜ 文字：{near_raw}",
        "severity": "high",
        "confidence": 0.7,
        "suggestion": f"人工核对原图：确认图中数字是否被局部修改（文字材料同位置为 {near_raw}）",
        "page": page,
    }


def _unverified_finding(value: str, context: str, page: int | None) -> dict:
    """分支 3：文字材料未读到该数字（OCR 漏读最可能）→ 待人工核验。"""
    label = context or "关键数字"
    return {
        "issue": f"{TAMPER_KIND_PREFIX}：图片数字未在文字材料中读到（待人工核验）",
        "reason": (
            f"图片中读到数字 {value}（{label}），文字材料未读到该数字、同位置也无其他数字——"
            "可能为 OCR 漏读小字数字，也可能为图片被局部修改，需人工核对原图"
        ),
        "original_text": f"{label} 图片：{value} ｜ 文字：未读到",
        "severity": "medium",
        "confidence": 0.45,
        "suggestion": (
            "人工核对原图：文字材料（OCR）未读到该数字，"
            "先确认图中数字是否真实存在，再判断是否篡改"
        ),
        "page": page,
    }


def _aggregate_finding(
    missing: list[tuple[str, str]], key_total: int, page: int | None
) -> dict:
    """聚合条目：文字层大面积未读到（OCR 质量低）时整档核对，不逐条轰炸。"""
    n = len(missing)
    pct = round(n * 100 / key_total) if key_total else 0
    preview = "、".join(f"{v}（{c or '关键数字'}）" for v, c in missing[:8])
    if n > 8:
        preview += f" 等 {n} 个"
    return {
        "issue": f"{TAMPER_KIND_PREFIX}：文字层未读到多数图片数字（待整档核对）",
        "reason": (
            f"图片中读到 {key_total} 个关键数字，其中 {n} 个未在文字材料中读到"
            f"（占比 {pct}%）——疑似该文档文字层（OCR）质量偏低，"
            "建议整档人工核对，而非逐条核验"
        ),
        "original_text": f"未读到：{preview}",
        "severity": "medium",
        "confidence": 0.4,
        "suggestion": "整档人工核对：文字层疑似大面积漏读，建议对照原图整档确认数字来源",
        "page": page,
    }


def check_tamper(
    vlm_numbers: list[dict],
    blocks: list[dict],
    page: int | None = 1,
    ocr_missing: list[dict] | None = None,
) -> list[dict]:
    """交叉校验（PR-6 三分支）：VLM 读出的关键数字 vs 文字材料数字集。

    vlm_numbers: [{"value": "9.85", "context": "年化收益率"}, ...]（来自
    visual_scan 的 visible_numbers 输出）。
    ocr_missing: visual_scan 的图片级预筛（VLM 读到、图片自身 OCR 文字层未
    读到）；提供时作为两阶段流水线的上游门——图片 OCR 明明读到过的数字
    不进入不一致判定（防误报），未提供时退化为内部自算（测试/独立调用）。
    返回与 vlm findings 同 schema 的 findings 列表（可疑才产出）。
    """
    if not vlm_numbers or not blocks:
        return []
    text = extract_text(blocks)
    text_nums = extract_text_numbers(blocks)
    missing_gate: set[str] | None = None
    if ocr_missing is not None:
        missing_gate = {
            norm_number(str(m.get("value") or ""))
            for m in ocr_missing
            if isinstance(m, dict)
        }

    changed: list[dict] = []
    unverified: list[dict] = []
    unverified_raw: list[tuple[str, str]] = []
    key_total = 0
    for item in vlm_numbers:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        context = str(item.get("context") or "").strip()
        if not value or not is_key_number(context, value):
            continue
        key_total += 1
        norm = norm_number(value)
        if norm in text_nums:
            continue  # 分支 1：文字集有且相等 → 一致
        if missing_gate is not None and norm not in missing_gate:
            # 上游说图片 OCR 读到过该数字，与文字集矛盾（脱敏/分块边界等）
            # ——信息不足，不做不一致判定（宁可少报，不误报确定性篡改）
            continue
        anchored = _locate_anchor_numbers(text, context)
        if anchored:
            # 分支 2：同位置有数字且不等 → 一票 changed（真篡改形态）
            _, near_raw = anchored[0]
            changed.append(_changed_finding(value, context, near_raw, page))
        else:
            # 分支 3：文字集无此数字 → 降级待人工核验
            unverified.append(_unverified_finding(value, context, page))
            unverified_raw.append((value, context))

    if len(unverified) >= _AGG_MIN and key_total and len(unverified) / key_total > _AGG_RATIO:
        return changed + [_aggregate_finding(unverified_raw, key_total, page)]
    return changed + unverified
