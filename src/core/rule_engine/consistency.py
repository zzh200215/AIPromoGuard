"""表格数字勾稽规则引擎（R2-2，对标恒生慧营勾稽检查项库）.

数字类违规（演示表算术对不上、宣传收益率超出演示区间）LLM 天然不可靠
（算术弱项），确定性勾稽是唯一解——双引擎叙事的第三块拼图（文本规则/
LLM 语义/表格勾稽）。

输入：markdown 表格块（R2-1 MinerU 通道的表格补充产物，"|"-行）+ 全文块。
流程：解析表格 → 表头语义映射（模板层）→ 按行执行勾稽检查项。

模板层设计（方案 Q2-2 的"表头异构"难点）：
- 字段模式库按**长模式优先**匹配（"预期年化收益率"命中 rate，不会被
  "预期收益"误吞——中间隔"年化"二字，子串不连续）；
- 覆盖率门禁：10 类典型表头样本中，字段识别正确（含"识别为不适配"）
  ≥70% 才允许勾稽上线——模板库随数据飞轮沉淀（未命中样本走 LLM 辅助
  映射的路径 v1 未实现，见方案 Q2-2，属后续增强）；
- 模板未识别的表**静默跳过**（零误报优先于召回——勾稽命中是 high 采信级，
  宁可漏一张怪表也不给人工塞垃圾）。

产出：与规则路同 schema 的 RuleHit（rule_id=None，confidence=1.0，
violation_type=consistency→落库走 rule 路自动确认）。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from src.core.rule_engine.engine import RuleHit
from src.parsers.base import TextBlock
from src.services.tamper_check import norm_number

# ---------- 表头语义映射模板库（字段 → 模式，长模式优先由匹配顺序保证） ----------

FIELD_PATTERNS: dict[str, list[str]] = {
    "principal": [
        "认购金额", "期初本金", "投资金额", "起点金额", "认购起点", "本金",
    ],
    "rate": [
        "预期年化收益率", "业绩比较基准", "年化收益率", "演示利率",
        "年化基准", "预期年化", "七日年化", "收益率", "年化",
    ],
    "profit": [
        "预期收益", "测算收益", "预计收益", "持有期收益", "收益金额",
        "到期收益", "投资收益", "对应收益",
    ],
    "total": [
        "期末金额", "本息合计", "期末合计", "到期金额", "到期本息",
        "期末总额", "合计",
    ],
    "days": [
        "持有天数", "持有时间", "持有期限", "投资期限", "期限", "天数",
    ],
}

# 明确不适配勾稽算术的表（识别后跳过，防止硬套公式产生垃圾命中）
_SKIP_DOMAINS = [
    "万份收益",  # 货币基金口径（万份收益/七日年化，无本金-收益勾稽关系）
    "现金价值",  # 保险现金价值表（精算口径）
    "保单年度",
    "累计保费",
]

_TOLERANCE = Decimal("0.01")  # 方案口径：算术容差 1%

_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_SEP_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_MD_CELLS = re.compile(r"(?<!\\)\|")
_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_RANGE_CELL_RE = re.compile(r"\d+(?:\.\d+)?\s*%?\s*[-~]\s*\d+(?:\.\d+)?")


def _cells(line: str) -> list[str]:
    """markdown 表格行 → 单元格列表（剥首尾空单元格）。"""
    parts = [c.strip() for c in _MD_CELLS.split(line)]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def parse_md_table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    """连续 | 行 → (表头 cells, 数据行 cells)。分隔行/非表格行返回 None。"""
    rows = [_cells(ln) for ln in lines if not _MD_SEP_ROW.match(ln)]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return None
    return rows[0], rows[1:]


def map_fields(header: list[str]) -> dict[str, int] | None:
    """表头 → {字段名: 列索引}；识别失败/不适配返回 None（静默跳过）。"""
    header_text = " ".join(header)
    if any(dom in header_text for dom in _SKIP_DOMAINS):
        return None
    mapping: dict[str, int] = {}
    for col_idx, cell in enumerate(header):
        for field, patterns in FIELD_PATTERNS.items():
            if field in mapping:
                continue
            if any(p in cell for p in patterns):
                mapping[field] = col_idx
                break
    return mapping if len(mapping) >= 2 else None


def _to_number(cell: str) -> Decimal | None:
    """单元格 → Decimal；含 % 的取数值本体（3.85% → 3.85）；失败返回 None。"""
    s = (cell or "").strip()
    if not s:
        return None
    m = _PCT_RE.search(s)
    if m:
        return Decimal(m.group(1))
    cleaned = norm_number(s)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _days_number(cell: str) -> Decimal | None:
    s = (cell or "").strip()
    m = re.search(r"(\d+)\s*天?", s)
    if m:
        return Decimal(m.group(1))
    return _to_number(s)


def _q(d: Decimal, places: str = "0.01") -> Decimal:
    return d.quantize(Decimal(places))


# ---------- 检查项 ----------

def _check_total(rows: list[list[str]], mapping: dict[str, int]) -> list[tuple[str, str]]:
    """期末金额 ≈ 本金 + 收益（容差 1% of 本金）。"""
    hits: list[tuple[str, str]] = []
    need = ("total", "principal", "profit")
    if not all(f in mapping for f in need):
        return hits
    for row in rows:
        try:
            total = _to_number(row[mapping["total"]])
            principal = _to_number(row[mapping["principal"]])
            profit = _to_number(row[mapping["profit"]])
        except IndexError:
            continue
        if total is None or principal is None or profit is None or principal == 0:
            continue
        expected = principal + profit
        if abs(total - expected) > abs(principal) * _TOLERANCE:
            hits.append(
                (
                    f"期末金额 {total} ≠ 本金 {principal} + 收益 {profit}",
                    " | ".join(c for c in row if c)[:80],
                )
            )
    return hits


def _check_profit_from_rate(
    rows: list[list[str]], mapping: dict[str, int]
) -> list[tuple[str, str]]:
    """收益 ≈ 本金 × 年化率 × 天数 / 365（四列齐才算；率/天数缺失的行跳过）。"""
    hits: list[tuple[str, str]] = []
    need = ("principal", "rate", "profit", "days")
    if not all(f in mapping for f in need):
        return hits
    for row in rows:
        try:
            rate_cell = row[mapping["rate"]]
            principal = _to_number(row[mapping["principal"]])
            profit = _to_number(row[mapping["profit"]])
            days = _days_number(row[mapping["days"]])
        except IndexError:
            continue
        if None in (principal, profit, days) or principal == 0:
            continue
        if rate_cell is None or _RANGE_CELL_RE.search(rate_cell):
            continue  # 区间单元格（"3.50%-4.50%"）算术语义模糊，跳过不硬算
        rate = _to_number(rate_cell)
        if rate is None:
            continue
        expected = principal * (rate / Decimal(100)) * days / Decimal(365)
        if abs(profit - expected) > abs(principal) * _TOLERANCE:
            hits.append(
                (
                    f"收益 {profit} ≠ 本金 {principal} × 年化 {rate}% × {days}天 / 365"
                    f"（测算 { _q(expected) }）",
                    " | ".join(c for c in row if c)[:80],
                )
            )
    return hits


def _rate_values(rows: list[list[str]], mapping: dict[str, int] | None) -> list[Decimal]:
    """提取 rate 数值集合：横向表头走映射列；转置表（字段在行首）走行扫描。"""
    rates: list[Decimal] = []
    if mapping and "rate" in mapping:
        for row in rows:
            try:
                v = _to_number(row[mapping["rate"]])
            except IndexError:
                continue
            if v is not None:
                rates.append(v)
        return rates
    # 转置兜底：某数据行首格命中 rate 模式 → 该行其余单元格数值即 rates
    rate_patterns = FIELD_PATTERNS["rate"]
    for row in rows:
        if not row:
            continue
        first = row[0]
        if any(p in first for p in rate_patterns):
            for cell in row[1:]:
                if _RANGE_CELL_RE.search(cell):
                    continue
                v = _to_number(cell)
                if v is not None:
                    rates.append(v)
            break
    return rates


def _check_rate_in_text(
    rates: list[Decimal], text_blocks: list[TextBlock]
) -> list[tuple[str, str]]:
    """正文宣称收益率必须落在 rate 数值集合的 [min, max] 区间内（跨位置一致）。"""
    hits: list[tuple[str, str]] = []
    if len(rates) < 2:  # 单值表格无"区间"语义，跳过（避免把正文正常引用当越界）
        return hits
    low, high = min(rates), max(rates)
    claimed: set[Decimal] = set()
    for b in text_blocks:
        for m in re.finditer(
            r"[\u4e00-\u9fff]{0,10}(?:收益率|基准|年化)[^\d%]{0,8}(\d+(?:\.\d+)?)\s*%",
            b.text or "",
        ):
            claimed.add(Decimal(m.group(1)))
    for v in sorted(claimed):
        if v < low or v > high:
            hits.append(
                (
                    f"正文宣称收益率 {v}% 超出演示表区间 [{low}% ~ {high}%]",
                    f"宣称值 {v}% vs 表格区间 {low}~{high}",
                )
            )
    return hits


# ---------- 主入口 ----------

def scan_consistency(blocks: list[TextBlock]) -> list[RuleHit]:
    """对文本块中的 markdown 表格执行勾稽扫描（内置，rule_id=None）。"""
    hits: list[RuleHit] = []
    # 收集表格块（连续 | 行）与全文文本（跨位置检查用）
    tables: list[list[str]] = []
    current: list[str] = []
    for b in blocks:
        for line in (b.text or "").splitlines():
            if _MD_TABLE_ROW.match(line) and line.count("|") >= 2:
                current.append(line)
            elif current:
                tables.append(current)
                current = []
    if current:
        tables.append(current)

    for table_lines in tables:
        parsed = parse_md_table(table_lines)
        if parsed is None:
            continue
        header, rows = parsed
        mapping = map_fields(header)
        if mapping is None:
            # 转置表兜底：字段在行首（情景矩阵"乐观/中性/悲观"形态）——
            # 仅支持跨位置收益率检查，算术勾稽项需要横向列，不适用
            rates = _rate_values(rows, None)
            if len(rates) < 2:
                continue
            for detail, evidence in _check_rate_in_text(rates, blocks):
                hits.append(_consistency_hit(detail, evidence))
            continue
        issues: list[tuple[str, str]] = []
        issues += _check_total(rows, mapping)
        issues += _check_profit_from_rate(rows, mapping)
        issues += _check_rate_in_text(_rate_values(rows, mapping), blocks)
        for detail, evidence in issues:
            hits.append(_consistency_hit(detail, evidence))
    return hits


# 维度身份前缀（与 pii_scan.PII_KIND_PREFIX 同模式，见其注释）
CONSISTENCY_KIND_PREFIX = "数字勾稽"


def _consistency_hit(detail: str, evidence: str) -> RuleHit:
    return RuleHit(
        rule_id=None,
        rule_name=f"{CONSISTENCY_KIND_PREFIX}：演示表算术不一致",
        domain="general",
        severity="high",
        rule_type="consistency",
        matched_text=evidence,
        char_start=0,
        char_end=0,
        page=None,
        paragraph=None,
        confidence=1.0,
        related_regulations=["《理财公司理财产品销售管理暂行办法》"],
        description=f"勾稽检查发现：{detail}",
    )
