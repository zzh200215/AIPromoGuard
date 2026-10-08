"""Spike：pdfplumber 文字版 PDF 表格识别率验证（PR-5 前置判据）.

背景（方案 PR-5）：勾稽引擎消费 markdown 表格块，当前只有 MinerU 通道能产出
（扫描件专用、CPU ~0.2 页/s、非默认开启）；文字版 PDF 的表格经 pypdf 提取是
乱序碎片，勾稽静默失效。本 spike 验证 **plan A** 的可行性：
用 pdfplumber 直读文字版 PDF 的表格（有文本层，无需 OCR/深解析）。

**预声明判据**（运行前定义，避免事后放宽）：
单个样本"识别成功" = ① 至少检出一个表格（≥2 行 ≥2 列）；② 该样本全部
ground-truth 关键数字都出现在提取单元格中（归一化后子串匹配）。
识别率 = 成功样本数 / 10。**≥8/10 → 按方案 A 实施；否则走降级方案 B**
（MinerU 默认开启 + 封面漏检区域告警）。

10 类样本覆盖：勾稽可算表（标准/年化×天数/业绩基准/费率/单位混排）×5、
跳过域名表（货基万份收益/保险现金价值）×2、难布局（合并单元格表头/全角混排/
跨页长表）×3。

产出：data/spike_pdfplumber/samples/*.pdf + report.json（与 spike_mineru 同惯例）。
用法："D:/AI/ACD/envs/llmXM/python.exe" scripts/spike/pdfplumber_table_spike.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pdfplumber
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "spike_pdfplumber"
SAMPLES_DIR = OUT_DIR / "samples"

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

_TITLE = ParagraphStyle("t", fontName="STSong-Light", fontSize=14, leading=18)
_NOTE = ParagraphStyle("n", fontName="STSong-Light", fontSize=9, leading=12,
                       textColor=colors.grey)


def _make_table(rows: list[list[str]], widths: list[int],
                spans: list[tuple[tuple[int, int], tuple[int, int]]] | None = None) -> Table:
    """spans 用 reportlab 约定 (列, 行)——注意不是 (行, 列)。"""
    t = Table(rows, colWidths=widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for start, end in spans or []:
        style.append(("SPAN", start, end))
    t.setStyle(TableStyle(style))
    return t


# ---------- 10 类典型表样本（含 ground truth 关键数字） ----------

SAMPLES: list[dict] = [
    {
        "id": "S01",
        "name": "收益演示表-标准四列",
        "expect": "勾稽可算（本金+收益=期末）",
        "title": "收益演示表（认购金额：100,000 元）",
        "rows": [
            ["认购金额（元）", "持有时间", "预期收益（元）", "期末金额（元）"],
            ["100,000.00", "90 天", "925.00", "100,925.00"],
            ["100,000.00", "180 天", "1,868.00", "101,868.00"],
            ["100,000.00", "366 天", "3,846.00", "103,846.00"],
        ],
        "widths": [130, 80, 110, 120],
        "numbers": ["100,000.00", "925.00", "100,925.00", "1,868.00",
                    "101,868.00", "3,846.00", "103,846.00"],
    },
    {
        "id": "S02",
        "name": "收益演示表-年化率×天数",
        "expect": "勾稽可算（本金×年化×天数/365）",
        "title": "收益率测算表",
        "rows": [
            ["认购金额（元）", "预期年化收益率", "持有天数", "预期收益（元）"],
            ["100,000.00", "3.85%", "90", "949.32"],
            ["100,000.00", "3.85%", "180", "1,898.63"],
            ["100,000.00", "3.85%", "366", "3,860.55"],
        ],
        "widths": [120, 130, 80, 110],
        "numbers": ["100,000.00", "3.85%", "90", "949.32", "180", "1,898.63",
                    "366", "3,860.55"],
    },
    {
        "id": "S03",
        "name": "业绩比较基准表-区间值",
        "expect": "字段部分识别（区间单元格跳过算术）",
        "title": "产品要素表",
        "rows": [
            ["产品名称", "业绩比较基准", "起购金额（元）", "风险等级"],
            ["XX稳健理财1号", "3.50%-4.50%", "10,000.00", "R2"],
            ["XX进取混合2号", "4.00%-6.00%", "50,000.00", "R3"],
        ],
        "widths": [120, 120, 110, 80],
        "numbers": ["3.50%-4.50%", "10,000.00", "4.00%-6.00%", "50,000.00"],
    },
    {
        "id": "S04",
        "name": "费率表-三档持有期",
        "expect": "识别费率列（持有期限 → days 映射）",
        "title": "费率表",
        "rows": [
            ["持有期限", "管理费率", "托管费率", "销售服务费率"],
            ["少于 7 天", "1.50%", "0.25%", "0.40%"],
            ["7 天至 30 天", "0.75%", "0.25%", "0.20%"],
            ["30 天以上", "0.00%", "0.25%", "0.00%"],
        ],
        "widths": [110, 90, 90, 120],
        "numbers": ["1.50%", "0.25%", "0.40%", "0.75%", "0.20%", "0.00%"],
    },
    {
        "id": "S05",
        "name": "货币基金表-万份收益（跳过域名）",
        "expect": "勾稽正确跳过（万份收益口径无本金-收益关系）",
        "title": "货币基金收益表现",
        "rows": [
            ["日期", "万份收益（元）", "七日年化收益率"],
            ["2026-09-28", "0.5210", "1.912%"],
            ["2026-09-29", "0.5187", "1.905%"],
            ["2026-09-30", "0.5233", "1.918%"],
        ],
        "widths": [120, 130, 140],
        "numbers": ["0.5210", "1.912%", "0.5187", "1.905%", "0.5233", "1.918%"],
    },
    {
        "id": "S06",
        "name": "保险现金价值表（跳过域名）",
        "expect": "勾稽正确跳过（精算口径）",
        "title": "现金价值示例表",
        "rows": [
            ["保单年度", "现金价值（元）", "累计保费（元）", "身故保额（元）"],
            ["第 1 年", "8,520.00", "10,000.00", "100,000.00"],
            ["第 2 年", "17,980.00", "20,000.00", "100,000.00"],
            ["第 3 年", "28,150.00", "30,000.00", "100,000.00"],
        ],
        "widths": [100, 120, 120, 120],
        "numbers": ["8,520.00", "10,000.00", "100,000.00", "17,980.00",
                    "20,000.00", "28,150.00", "30,000.00"],
    },
    {
        "id": "S07",
        "name": "单位混排表-万元/元",
        "expect": "勾稽可算（单位归一化：5万元+2,100元=5.21万元）",
        "title": "收益演示表（单位：万元）",
        "rows": [
            ["认购金额", "持有期限", "预期收益", "期末金额"],
            ["5 万元", "180 天", "2,100 元", "5.21 万元"],
            ["10 万元", "180 天", "4,200 元", "10.42 万元"],
        ],
        "widths": [110, 100, 110, 110],
        "numbers": ["5 万元", "2,100 元", "5.21 万元", "10 万元", "4,200 元", "10.42 万元"],
    },
    {
        "id": "S08",
        "name": "合并单元格表头-情景矩阵",
        "expect": "结构还原（跨列合并表头）",
        "title": "情景演示表",
        "rows": [
            ["情景", "对应收益（元）", "", ""],
            ["", "乐观", "中性", "悲观"],
            ["年化收益率", "4.20%", "3.85%", "2.10%"],
            ["100,000 元本金", "4,200.00", "3,850.00", "2,100.00"],
        ],
        "widths": [130, 100, 100, 100],
        "spans": [((1, 0), (3, 0))],  # 表头行"对应收益（元）"跨列 1-3（reportlab (列,行) 约定）
        "numbers": ["4.20%", "3.85%", "2.10%", "4,200.00", "3,850.00", "2,100.00"],
    },
    {
        "id": "S09",
        "name": "全角数字混排",
        "expect": "全角→半角归一后勾稽可算",
        "title": "收益速览表",
        "rows": [
            ["认购金额（元）", "年化收益率", "预期收益（元）"],
            ["１００，０００", "３．８５％", "９４９.３２"],
            ["２００，０００", "３．８５％", "１，８９８.６３"],
        ],
        "widths": [140, 120, 130],
        "numbers": [
            "１００，０００", "３．８５％", "９４９.３２", "２００，０００", "１，８９８.６３",
        ],
    },
    {
        "id": "S10",
        "name": "跨页长表-页1表头页2续行",
        "expect": "跨页拆分可检出（数字不丢）",
        "title": "收益演示表（36 期）",
        "rows": [["期数", "认购金额（元）", "持有期限", "预期收益（元）"]]
        + [[f"第 {i} 期", "100,000.00", f"{i * 10} 天", f"{i * 105}.00"]
           for i in range(1, 37)],
        "widths": [80, 130, 100, 110],
        "numbers": ["315.00", "3,780.00", "100,000.00", "360 天"],
        "cross_page": True,
    },
]


def _normalize(text: str) -> str:
    """归一化（全角→半角、去空白/逗号）——只用于关键数字召回比对。"""
    table = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")
    return (
        (text or "")
        .translate(table)
        .replace(" ", "")
        .replace(",", "")
        .replace("\u3000", "")
    )


def _build_pdf(sample: dict) -> Path:
    path = SAMPLES_DIR / f"{sample['id']}_{sample['name'].split('-')[0]}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=sample["id"])
    flow = [Paragraph(sample["title"], _TITLE), Spacer(1, 12)]
    flow.append(_make_table([list(r) for r in sample["rows"]], sample["widths"],
                            sample.get("spans")))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph("注：本表为演示样例，不构成收益承诺。", _NOTE))
    doc.build(flow)
    return path


def _extract(path: Path) -> tuple[list[list[list[str]]], int, int]:
    """返回 (所有页提取的表格, 页数, 文本层字符数)。"""
    tables: list[list[list[str]]] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        text_len = 0
        for page in pdf.pages:
            text_len += len(page.extract_text() or "")
            for t in page.extract_tables():
                tables.append([[c if c is not None else "" for c in row] for row in t])
    return tables, page_count, text_len


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    started = time.time()
    for sample in SAMPLES:
        path = _build_pdf(sample)
        t0 = time.time()
        tables, page_count, text_len = _extract(path)
        elapsed = time.time() - t0

        normalized_cells = [
            _normalize(c)
            for t in tables for row in t for c in row if c
        ]
        missed = [
            n for n in sample["numbers"]
            if not any(_normalize(n) in cell for cell in normalized_cells)
        ]
        recalled = len(sample["numbers"]) - len(missed)
        # 判定：① 检出表格（≥2 行 ≥2 列） ② 关键数字全召回
        found_table = any(
            len(t) >= 2 and max((len(r) for r in t), default=0) >= 2 for t in tables
        )
        ok = found_table and not missed
        rows_total = sum(len(t) for t in tables)
        results.append({
            "id": sample["id"],
            "name": sample["name"],
            "expect": sample["expect"],
            "table_found": found_table,
            "tables": len(tables),
            "rows_total": rows_total,
            "expected_rows": len(sample["rows"]),
            "pages": page_count,
            "text_layer_chars": text_len,
            "numbers_total": len(sample["numbers"]),
            "numbers_recalled": recalled,
            "missed": missed,
            "elapsed_s": round(elapsed, 3),
            "ok": ok,
            "pdf": str(path.relative_to(ROOT)),
        })
        mark = "✓" if ok else "✗"
        extra = f"，缺失 {missed}" if missed else ""
        print(f"{mark} {sample['id']} {sample['name']}：表 {len(tables)} 个/{rows_total} 行"
              f"（{page_count} 页），数字 {recalled}/{len(sample['numbers'])}{extra}")

    passed = sum(1 for r in results if r["ok"])
    report = {
        "engine": "pdfplumber",
        "engine_version": getattr(pdfplumber, "__version__", "?"),
        "criterion": "① 检出表格(≥2行≥2列)且 ② 全部关键数字召回（归一化子串匹配）",
        "samples": results,
        "passed": passed,
        "total": len(results),
        "recognition_rate": round(passed / len(results), 4),
        "threshold": 0.8,
        "verdict": "plan_a_go" if passed / len(results) >= 0.8 else "plan_b_fallback",
        "elapsed_seconds": round(time.time() - started, 2),
    }
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n识别率 {passed}/{len(results)} = {report['recognition_rate']:.0%}"
          f"（阈值 {report['threshold']:.0%}）→ {report['verdict']}")
    print(f"报告：{OUT_DIR / 'report.json'}")


if __name__ == "__main__":
    main()
