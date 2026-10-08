"""文字版 PDF 表格通道单测（PR-5）：pdfplumber 抽表 → markdown 块 → 勾稽消费.

覆盖（对齐 PR-5 验收标准）：
- 10 类典型表样本：① 表格块被追加（识别成功）；② 勾稽字段映射语义正确
  （可算表 mapping 命中 / 货基·保险域名正确跳过 / 合并表头走转置兜底）；
- 主路零变化：pypdf 文本块逐字节不变（封面装饰区文本块行为不变）；
- 勾稽从失效到生效：同一份"算术错误"PDF，补表前 0 命中、补表后必命中；
- 降级与幂等：pdfplumber 异常不阻断主路；重复合并不重复补块；
- 接线：document_service 配置开关（pdf_tables_enabled）。

样本定义复用 spike 脚本（单一事实来源）：scripts/spike/pdfplumber_table_spike.py。
依赖缺失（pdfplumber/reportlab 未装）时整体 skip。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

from src.core.rule_engine.consistency import (  # noqa: E402
    _rate_values,
    map_fields,
    parse_md_table,
    scan_consistency,
)
from src.parsers.base import ParsedDocument  # noqa: E402
from src.parsers.pdf_parser import PdfParser  # noqa: E402
from src.parsers.pdf_table_adapter import (  # noqa: E402
    extract_tables,
    merge_pdf_tables,
    table_to_markdown,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_spike():
    spec = importlib.util.spec_from_file_location(
        "pdfplumber_table_spike", ROOT / "scripts" / "spike" / "pdfplumber_table_spike.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def spike():
    return _load_spike()


@pytest.fixture
def build(tmp_path, monkeypatch, spike):
    """样本 → PDF 落 tmp；返回 (samples_by_id, build_fn)。"""
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)  # spike.main 才会建目录，测试自建
    monkeypatch.setattr(spike, "SAMPLES_DIR", samples_dir)

    def _build(sample_id: str) -> Path:
        sample = next(s for s in spike.SAMPLES if s["id"] == sample_id)
        return spike._build_pdf(sample)

    return {s["id"]: s for s in spike.SAMPLES}, _build


def _table_marks(doc: ParsedDocument) -> list[str]:
    return [b.text for b in doc.blocks if b.text.lstrip().startswith("|")]


def _first_mapping(doc: ParsedDocument) -> dict | None:
    """取第一个表格块的字段映射（勾稽入口的等价调用）。"""
    for mark in _table_marks(doc):
        parsed = parse_md_table(mark.splitlines())
        if parsed is None:
            continue
        header, _rows = parsed
        return map_fields(header)
    return None


# 10 类样本的勾稽语义预期（引擎口径实测锁定，见 consistency.py 模板库与跳过域名）：
#   fields=None 表示映射不足 2 字段或命中跳过域名 → 静默跳过（零误报优先）
_EXPECT = {
    "S01": {"fields": {"principal", "days", "profit", "total"}},
    "S02": {"fields": {"principal", "rate", "days", "profit"}},
    # 业绩比较基准→rate 命中，但"起购金额"不在 principal 模板库 → 仅 1 字段 → 跳过
    # （模板库覆盖缺口，如实锁定；补库属后续数据飞轮工作，不在 PR-5 范围）
    "S03": {"fields": None, "transpose_rates": 0},
    "S04": {"fields": None, "transpose_rates": 0},   # 仅 days，费率表无勾稽关系
    "S05": {"fields": None, "transpose_rates": 0},   # 万份收益（货基口径）→ 跳过
    "S06": {"fields": None, "transpose_rates": 0},   # 保单年度/现金价值（精算口径）→ 跳过
    "S07": {"fields": {"principal", "days", "profit", "total"}},
    # 合并表头：表头字段不足 → 转置兜底（行首"年化收益率"）取到 3 个收益率
    "S08": {"fields": None, "transpose_rates": 3},
    "S09": {"fields": {"principal", "rate", "profit"}},
    "S10": {"fields": {"principal", "days", "profit"}},
}


def test_ten_samples_table_channel(build):
    """10 类样本：补表成功 + 字段映射语义正确 + 主路块零变化 + 无假阳性. """
    samples, build_pdf = build
    for sid, expect in _EXPECT.items():
        assert samples[sid], f"{sid}: 样本定义缺失"
        path = build_pdf(sid)
        baseline = PdfParser().parse(path)
        baseline_texts = [b.text for b in baseline.blocks]
        baseline_hits = scan_consistency(baseline.blocks)
        assert baseline_hits == [], f"{sid}: 纯文本层不应有勾稽命中（通道要解决的问题）"

        appended = merge_pdf_tables(baseline, path)
        assert appended >= 1, f"{sid}: 未补入表格块（识别失败）"
        # 主路零变化：既有块逐字节不变
        assert [b.text for b in baseline.blocks[: len(baseline_texts)]] == baseline_texts

        mapping = _first_mapping(baseline)
        if expect["fields"] is None:
            assert mapping is None, f"{sid}: 应跳过（域名/字段不足），实际 {mapping}"
        else:
            assert mapping is not None, f"{sid}: 字段映射失败"
            assert expect["fields"] <= set(mapping), f"{sid}: 映射缺字段 {mapping}"

        if "transpose_rates" in expect:
            rates = []
            for parsed in (parse_md_table(m.splitlines()) for m in _table_marks(baseline)):
                if parsed:
                    rates = _rate_values(parsed[1], None)
                    if rates:
                        break
            assert len(rates) == expect["transpose_rates"], f"{sid}: 转置兜底取数 {rates}"

        assert scan_consistency(baseline.blocks) == [], f"{sid}: 一致表不应有勾稽命中"


def test_consistency_from_broken_to_working(tmp_path):
    """勾稽从失效到生效：算术错误表在纯文本层 0 命中，补表后必命中。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    rows = [
        ["认购金额（元）", "持有时间", "预期收益（元）", "期末金额（元）"],
        ["100,000.00", "90 天", "2,925.00", "100,925.00"],  # 算术错误：100,000+2,925≠100,925
    ]
    path = tmp_path / "broken_math.pdf"
    style = ParagraphStyle("cn", fontName="STSong-Light", fontSize=11, leading=15)
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    tbl = Table(rows, colWidths=[130, 80, 110, 120])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.grey),
    ]))
    doc.build([Paragraph("收益演示表", style), tbl])

    parsed = PdfParser().parse(path)
    assert scan_consistency(parsed.blocks) == []  # 纯文本层：勾稽不可见

    appended = merge_pdf_tables(parsed, path)
    assert appended == 1
    hits = scan_consistency(parsed.blocks)
    assert len(hits) == 1
    assert "期末金额" in hits[0].description


def test_markdown_shape_and_escaping():
    """markdown 形态：表头分隔行、单元格内竖线转义、空单元格保留。"""
    mark = table_to_markdown([
        ["A|B", "C"],
        [" x\ny ", ""],
    ])
    lines = mark.splitlines()
    assert lines[0] == r"| A\|B | C |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == r"| x y |  |"


def test_merge_is_idempotent(build):
    """重复合并不重复补块（dedupe：块已含相同 markdown）。"""
    _samples, build_pdf = build
    path = build_pdf("S01")
    doc = PdfParser().parse(path)
    assert merge_pdf_tables(doc, path) == 1
    assert merge_pdf_tables(doc, path) == 0


def test_graceful_degradation(monkeypatch, build):
    """pdfplumber 异常时返回 0 且不改动主路（降级为纯文本层）。"""
    _samples, build_pdf = build
    path = build_pdf("S01")
    doc = PdfParser().parse(path)
    before = [b.text for b in doc.blocks]

    import pdfplumber

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(pdfplumber, "open", _boom)
    assert extract_tables(path) == []
    assert merge_pdf_tables(doc, path) == 0
    assert [b.text for b in doc.blocks] == before


def test_document_service_config_toggle(monkeypatch, build):
    """接线：pdf_tables_enabled 开/关决定是否补表（主路始终保留）。"""
    from src.services.document_service import document_service

    _samples, build_pdf = build
    path = build_pdf("S01")

    doc_on = document_service._parse_text_layer(str(path), {"pdf_tables_enabled": True})
    doc_off = document_service._parse_text_layer(str(path), {"pdf_tables_enabled": False})
    assert _table_marks(doc_on), "开启时应有表格块"
    assert _table_marks(doc_off) == [], "关闭时不应有表格块"
    # 两条路径的 pypdf 主路一致
    assert [b.text for b in doc_on.blocks[: len(doc_off.blocks)]] == [
        b.text for b in doc_off.blocks
    ]
