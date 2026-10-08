"""文字版 PDF 表格通道（PR-5）：pdfplumber 抽表 → markdown 表格块（MinerU 同构）.

背景：勾稽引擎（R2-2）消费 markdown 表格块，此前只有 MinerU 通道能产出——
MinerU 是扫描件通道（CPU ~0.2 页/s、默认关闭）；**文字版 PDF** 的表格经 pypdf
提取是乱序碎片（表格线/列对齐丢失），勾稽静默失效。本适配器用 pdfplumber
直读文字版 PDF 的表格网格（spike 预声明判据 10/10 通过，见
data/spike_pdfplumber/report.json），产出与 MinerU 通道**同构**的 markdown
表格块，供 chunker 与勾稽规则原样消费。

设计约束（对齐 R2-1 混合通道的"只补不替"原则）：
- 主路永远是 pypdf 文本层（页码、封面装饰区文本块完整）——本适配器只
  **追加**表格块（page=None），不修改/删除任何既有块；
- 去重：文本层已含相同表格（MinerU 已补过 / pypdf 恰好逐行提取）时跳过；
- 失败降级：pdfplumber 不可用或解析异常 → 记日志返回 0，主路不受影响；
- 数字互校：表格通道与文本层的数字集合差异记日志（与 MinerU 通道同口径），
  "表格独有"的数字正是勾稽通道的价值所在，"文本层独有"提示抽取可能漏行。

页码语义：表格块 page=None（报告定位显示"-"）——与 MinerU 通道一致，
表格勾稽不依赖页码。
"""

from __future__ import annotations

from pathlib import Path

from src.parsers.base import ParsedDocument, TextBlock
from src.parsers.mineru_parser import cross_check_numbers
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MIN_ROWS = 2  # 表头 + 至少 1 数据行
_MIN_COLS = 2


def table_to_markdown(rows: list[list[str]]) -> str:
    """二维单元格 → markdown 表格（表头 + 分隔行 + 数据行），MinerU 同构.

    - 单元格内换行/多余空白压成单空格；`|` 转义为 `\\|`（勾稽层的单元格
      切分正则 `(?<!\\\\)\\|` 与转义约定配套）；
    - 分隔行 `| --- |`：与 MinerU markdown 输出一致，勾稽层 `parse_md_table`
      会自动跳过分隔行。
    """
    lines: list[str] = []
    for idx, row in enumerate(rows):
        cells = [
            (c or "").replace("|", "\\|").replace("\n", " ").strip()
            for c in row
        ]
        lines.append("| " + " | ".join(cells) + " |")
        if idx == 0:
            lines.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(lines)


def extract_tables(path: str | Path) -> list[list[list[str]]]:
    """pdfplumber 逐页抽表，返回单元格网格列表（含表头行）.

    仅处理"线框表格"（extract_tables 默认 lines 策略）——无框线靠空白分列的
    版式（多为排版噪声）不在本通道目标内，宁缺勿滥。
    """
    grids: list[list[list[str]]] = []
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    grid = [
                        [(cell if cell is not None else "") for cell in row]
                        for row in table
                    ]
                    if len(grid) >= _MIN_ROWS and max(len(r) for r in grid) >= _MIN_COLS:
                        grids.append(grid)
    except Exception as exc:  # noqa: BLE001 — 未安装/抽取失败均不阻断主路
        logger.warning("pdfplumber 表格抽取失败（降级为纯文本层）: %s: %s", path, exc)
        return []
    return grids


def merge_pdf_tables(
    doc: ParsedDocument, path: str | Path, *, check_numbers: bool = True
) -> int:
    """把 PDF 表格以 markdown 块追加进 doc（只补不替），返回追加块数.

    去重口径：表格 markdown 与既有块文本完全相同、或既有文本层已含该表格的
    全部行（如 pypdf 逐行提取 + 行内恰好带 |），跳过不重复补。
    """
    grids = extract_tables(path)
    if not grids:
        return 0

    layer_text = "\n".join(b.text for b in doc.blocks)
    normalized_layer = layer_text.replace(" ", "")
    marks: list[str] = []
    appended = 0
    for grid in grids:
        markdown = table_to_markdown(grid)
        if markdown in layer_text:
            continue
        # 逐行包含判定：表格每一行（去空格后）都已出现在文本层 → 视为已覆盖
        rows_in_layer = all(
            line.replace(" ", "") in normalized_layer
            for line in markdown.splitlines()
            if not line.startswith("| ---")
        )
        if rows_in_layer:
            continue
        doc.blocks.append(
            TextBlock(text=markdown, page=None, paragraph=len(doc.blocks) + 1)
        )
        marks.append(markdown)
        appended += 1

    if check_numbers and marks:
        diff = cross_check_numbers("\n".join(marks), layer_text)
        if diff["mineru_only"]:
            logger.info(
                "PDF 表格通道：文本层缺失的数字（表格补充的价值点）: %s",
                diff["mineru_only"][:10],
            )
        if diff["text_only"]:
            logger.info(
                "PDF 表格通道：文本层独有数字（抽取可能漏行，勾稽重点核对）: %s",
                diff["text_only"][:10],
            )
    if appended:
        logger.info("PDF 表格通道：追加 %s 个 markdown 表格块（%s）", appended, path)
    return appended
