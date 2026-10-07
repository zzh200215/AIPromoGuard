"""Spike：MinerU 4.x 本机解析质量验证（R2-1/R2-2 前置判据）.

直接调 Python API（MinerUParser），绕过 4.x doclib/server 架构（其 daemon
模式在本机 SQLite 只读写崩溃，与解析质量无关）。

评估点（对照 make_test_pdf.py 的 ground truth）：
  1. 关键数字完整性：页1 大字/区间/金额/期限 + 页2 两张表全部数字
  2. 表格结构还原：页2 两张表是否输出为 markdown 表格（含表头行）
  3. 耗时（含首次模型下载单独记录）

用法："D:/AI/ACD/envs/llmXM/python.exe" scripts/spike/mineru_parse_test.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MINERU_MODEL_SOURCE", "modelscope")

PDF = ROOT / "data" / "spike_mineru" / "test_marketing.pdf"
OUT_DIR = ROOT / "data" / "spike_mineru"

# ground truth（与 make_test_pdf.py 一致；千分位归一后比对）
GT_NUMBERS = [
    "3.85", "3.50", "4.50", "50000", "366",
    "2026", "10", "8", "15", "1234567890123",
    "100000", "90", "180", "1.20", "925.00", "100925.00",
    "1868.00", "101868.00", "3846.00", "103846.00",
    "4.20", "2.10", "4200.00", "3850.00", "2100.00", "0.25",
]


def norm_num(s: str) -> str:
    s = s.replace(",", "").replace("，", "").rstrip(".")
    try:
        return f"{float(s):g}"
    except ValueError:
        return s


def main() -> None:
    from mineru.parser.mineru_parser import MinerUParser

    t0 = time.time()
    parser = MinerUParser(tier="standard")
    result = parser.parse(PDF)
    elapsed = time.time() - t0

    # 导出 markdown：markdown() 是方法（v2 修正：4.x ParseResult 的 markdown 为 lazy 方法）
    try:
        md = result.markdown()
    except Exception:  # noqa: BLE001
        md = str(result)
    (OUT_DIR / "parsed.md").write_text(md, encoding="utf-8")

    # 数字完整性
    flat = norm_num(re.sub(r"\s+", " ", md))
    found, missed = [], []
    for g in GT_NUMBERS:
        (found if norm_num(g) in flat else missed).append(g)

    # 表格结构：markdown 表格行数
    table_rows = [ln for ln in md.splitlines() if ln.strip().startswith("|")]
    tables = []
    cur: list[str] = []
    for ln in md.splitlines():
        if ln.strip().startswith("|"):
            cur.append(ln)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)

    report = {
        "mineru_version": _pkg_version(),
        "tier": "standard",
        "elapsed_seconds": round(elapsed, 1),
        "gt_numbers": len(GT_NUMBERS),
        "numbers_found": len(found),
        "numbers_missed": missed,
        "number_recall": round(len(found) / len(GT_NUMBERS), 4),
        "markdown_table_blocks": len([t for t in tables if len(t) >= 2]),
        "table_lines_total": len(table_rows),
        "md_chars": len(md),
    }
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n--- parsed.md 前 60 行 ---")
    print("\n".join(md.splitlines()[:60]))


def _pkg_version() -> str:
    try:
        from importlib.metadata import version
        return version("mineru")
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    main()
