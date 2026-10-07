"""勾稽规则引擎单测（R2-2）：表头映射覆盖率门禁 + 三组检查项正负样本.

开工门禁（产品升级方案.md Q2-2）：10 类典型演示表表头中，字段识别正确
（含"识别为不适配跳过"）≥70%。样本即 spike 数据，随模板库演进扩充。
"""


from src.core.rule_engine.consistency import (
    map_fields,
    parse_md_table,
    scan_consistency,
)
from src.parsers.base import TextBlock

# ---------- 10 类异构表头（覆盖率 spike 数据） ----------
# 每项: (表头行, 期望识别的字段集合)；期望 None = 应识别为不适配跳过

HEADER_SAMPLES: list[tuple[str, set[str] | None]] = [
    # 1. 标准版
    ("| 持有时间 | 管理费率 | 预期收益（元） | 期末金额（元） |",
     {"days", "profit", "total"}),
    # 2. 本金版
    ("| 期初本金 | 年化收益率 | 预期收益 | 本息合计 |",
     {"principal", "rate", "profit", "total"}),
    # 3. 基准版
    ("| 认购金额 | 业绩比较基准 | 测算收益 | 到期金额 |",
     {"principal", "rate", "profit", "total"}),
    # 4. 天数版
    ("| 持有天数 | 演示利率 | 收益金额 | 期末总额 |",
     {"days", "rate", "profit", "total"}),
    # 5. 期限版
    ("| 投资期限 | 年化基准 | 预计收益 | 到期本息 |",
     {"days", "rate", "profit", "total"}),
    # 6. 括号异构
    ("| 持有时间(天) | 管理费率(%) | 预期收益(元) | 期末金额(元) |",
     {"days", "profit", "total"}),
    # 7. 货基版（无本金-收益勾稽关系，应识别为不适配）
    ("| 日期 | 万份收益 | 七日年化 |", None),
    # 8. 保险版（精算口径，应识别为不适配）
    ("| 保单年度 | 年度保费 | 累计保费 | 现金价值 |", None),
    # 9. 三列简版
    ("| 期限 | 收益率 | 到期收益 |", {"days", "rate", "profit"}),
    # 10. 到期版
    ("| 认购起点 | 预期年化 | 到期收益 | 到期金额 |",
     {"principal", "rate", "profit", "total"}),
]


def test_header_mapping_coverage_gate():
    """开工门禁：字段识别正确率 ≥70%（含"正确跳过"）。"""
    ok = 0
    for header_line, expected in HEADER_SAMPLES:
        header, _ = parse_md_table([header_line, "| 1 | 2 | 3 | 4 |"])
        mapping = map_fields(header)
        if expected is None:
            ok += mapping is None
        else:
            ok += mapping is not None and expected.issubset(set(mapping))
    assert ok / len(HEADER_SAMPLES) >= 0.7, f"覆盖率 {ok}/{len(HEADER_SAMPLES)} 未达标"


def test_parse_md_table_skips_separator():
    header, rows = parse_md_table(
        ["| 持有时间 | 预期收益 |", "| --- | --- |", "| 90天 | 925.00 |"]
    )
    assert header == ["持有时间", "预期收益"]
    assert rows == [["90天", "925.00"]]


# ---------- 检查项：表内一致（期末 = 本金 + 收益） ----------

_HEADER_5COL = "| 认购金额 | 持有时间 | 管理费率 | 预期收益（元） | 期末金额（元） |"


def _table_block(rows: list[str]) -> TextBlock:
    sep = "| --- | --- | --- | --- | --- |"
    return TextBlock(text="\n".join([_HEADER_5COL, sep, *rows]))


def test_total_consistency_hit():
    # 期末 200,000 ≠ 本金 100,000 + 收益 3,850 —— 算术对不上
    block = _table_block(
        ["| 100,000 | 90天 | 1.20% | 3,850.00 | 200,000.00 |"]
    )
    hits = scan_consistency([block])
    assert len(hits) == 1
    assert hits[0].rule_type == "consistency"
    assert hits[0].severity == "high"
    assert hits[0].confidence == 1.0
    assert hits[0].rule_id is None
    assert "期末金额" in hits[0].description


def test_total_consistency_pass_no_hit():
    block = _table_block(
        ["| 100,000 | 90天 | 1.20% | 3,850.00 | 103,850.00 |"]
    )
    assert scan_consistency([block]) == []


_ROW_5COL_TEMPLATE = "| 100,000 | 90天 | {rate} | {profit} | {total} |"


def _profit_rate_block(rate: str, profit: str, total: str) -> TextBlock:
    header = "| 期初本金 | 持有天数 | 年化收益率 | 预期收益 | 本息合计 |"
    row = _ROW_5COL_TEMPLATE.format(rate=rate, profit=profit, total=total)
    return TextBlock(text="\n".join([header, "| --- | --- | --- | --- | --- |", row]))


def test_profit_from_rate_hit():
    # 收益 9,625 ≠ 100,000 × 3.85% × 90/365 ≈ 949.32 —— 差一个数量级
    hits = scan_consistency([_profit_rate_block("3.85%", "9,625.00", "109,625.00")])
    assert len(hits) == 1
    assert "9625" in hits[0].description and "949.32" in hits[0].description


def test_profit_from_rate_pass():
    # 100,000 × 3.85% × 90/365 = 949.32 ≈ 950（容差 1% of 本金 = 1000，通过）
    block = _profit_rate_block("3.85%", "949.32", "100,949.32")
    assert scan_consistency([block]) == []


def test_range_rate_cell_skipped():
    """区间利率单元格（3.50%-4.50%）算术语义模糊，跳过不硬算。"""
    block = _profit_rate_block("3.50%-4.50%", "9,625.00", "109,625.00")
    assert scan_consistency([block]) == []


def test_money_fund_table_skipped():
    """货基表（万份收益）不适配勾稽，零命中零误报。"""
    block = TextBlock(
        text="| 日期 | 万份收益 | 七日年化 |\n| --- | --- | --- |\n| 10-08 | 0.6412 | 2.35% |"
    )
    assert scan_consistency([block]) == []


# ---------- 检查项：跨位置（正文宣称 vs 表格区间） ----------

def test_claimed_rate_above_table_range():
    table = TextBlock(
        text="\n".join(
            [
                "| 情景 | 乐观 | 中性 | 悲观 |",
                "| --- | --- | --- | --- |",
                "| 年化收益率 | 4.20% | 3.85% | 2.10% |",
            ]
        )
    )
    claim = TextBlock(text="产品宣传页标注：预期年化收益率 5.80%")
    hits = scan_consistency([table, claim])
    assert any("超出" in h.description for h in hits)


def test_claimed_rate_within_range_pass():
    table = TextBlock(
        text="\n".join(
            [
                "| 情景 | 乐观 | 中性 | 悲观 |",
                "| --- | --- | --- | --- |",
                "| 年化收益率 | 4.20% | 3.85% | 2.10% |",
            ]
        )
    )
    claim = TextBlock(text="业绩比较基准 3.85%，详见演示表")
    assert scan_consistency([table, claim]) == []


def test_single_value_table_no_range_semantics():
    """单值利率表没有"区间"语义，正文引用不构成越界。"""
    table = TextBlock(
        text="\n".join(["| 期初本金 | 年化收益率 |", "| --- | --- |", "| 100,000 | 3.85% |"])
    )
    claim = TextBlock(text="宣传单称预期年化收益率 9.99%")
    assert scan_consistency([table, claim]) == []


# ---------- 端到端：MinerU 表格块 → 勾稽（R2-1 + R2-2 串联） ----------

def test_mineru_table_block_end_to_end():
    """模拟 MinerU 补入的表格块（markdown 原样、page=None）直接被勾稽消费。"""
    mineru_table = TextBlock(
        text=(
            "| 认购金额 | 持有时间 | 管理费率 | 预期收益（元） | 期末金额（元） |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 100,000 | 366天 | 1.20% | 3,846.00 | 999,999.00 |"
        ),
        page=None,
        paragraph=5,
    )
    hits = scan_consistency([mineru_table])
    assert len(hits) == 1
    assert hits[0].page is None
    assert "999,999" in hits[0].matched_text
