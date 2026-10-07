"""MinerU 深解析通道（R2-1）：扫描件 PDF 全文解析 + 表格结构化补充.

分工（spike 结论驱动，见 data/spike_mineru/report.json）：
- pypdf 文本层（PdfParser 主路）有页码、有正文，但对扫描件无能为力
  （直接 422 拒绝）、对表格只有乱序碎片；
- MinerU（4.x Python API，spike：表格 100% 还原、数字召回 96.2%、
  CPU ~0.2 页/s）补两个洞：① 扫描件 PDF 全文解析（替代 422 报错）；
  ② 表格块补入主路（markdown 表格原样进 blocks，供勾稽规则消费）；
- 已知代价（spike 发现）：MinerU 会静默漏检封面装饰区文本块（含风险
  提示行）——因此**主路永远是 pypdf 文本层**（有内容时），MinerU 只补
  不替；互校对账（两边数字集合差异）记日志，差异块由勾稽/人工兜底。

页码语义：MinerU 补入块 page=None（报告定位显示"-"）——表格勾稽不依赖
页码，可接受的 v1 取舍。

集成方式：直接调 Python API（MinerUParser），不走 4.x 的 CLI/server
（daemon 在本机有 SQLite readonly 崩溃 bug，见 spike 记录）。import 惰性：
未安装 mineru 的环境不影响解析链其余部分。
"""

from __future__ import annotations

import re
from pathlib import Path

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _is_table_row(line: str) -> bool:
    return bool(_MD_TABLE_ROW.match(line)) and line.count("|") >= 2


def _split_table_blocks(markdown: str) -> list[str]:
    """从 MinerU markdown 提取表格块（连续 | 行合并为一块，保留 markdown 原样）。"""
    tables: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if _is_table_row(line):
            current.append(line.strip())
        elif current:
            tables.append("\n".join(current))
            current = []
    if current:
        tables.append("\n".join(current))
    return tables


def parse_pdf_deep(path: str | Path, tier: str = "standard") -> ParsedDocument:
    """MinerU 深解析：全文 markdown 切块（page=None）。

    仅扫描件（文本层为空）时作为唯一文本来源；文字版 PDF 走 parse_pdf_hybrid。
    """
    result = _engine_parse(path, tier)
    paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()
    ]
    if not paragraphs:
        # 与 PdfParser 的扫描件 422 同口径：空结果静默通过属高危漏检
        raise ValueError("MinerU 解析结果为空（图片可能无法识别）")
    blocks = [
        TextBlock(text=p, page=None, paragraph=i)
        for i, p in enumerate(paragraphs, start=1)
    ]
    return ParsedDocument(
        file_name=Path(path).name,
        title=blocks[0].text[:80],
        blocks=blocks,
    )


def _engine_parse(path: str | Path, tier: str) -> str:
    """惰性加载 MinerU 引擎并返回 markdown 全文（唯一与 mineru 包的耦合点，测试 mock 此处）。"""
    from mineru.parser.mineru_parser import MinerUParser as _Engine

    return _Engine(tier=tier).parse(path).markdown()


def parse_pdf_hybrid(
    path: str | Path, tier: str = "standard", text_layer: ParsedDocument | None = None
) -> ParsedDocument:
    """混合解析（文字版 PDF 的推荐路径）：pypdf 文本层为主路，MinerU 只补不替.

    - 主路：text_layer（PdfParser 输出，有页码）——风险提示/正文段落以它为准，
      规避 spike 发现的 MinerU 静默漏块问题；
    - 补充①：MinerU markdown 表格块（page=None）——文本层的表格是乱序碎片，
      markdown 表格供勾稽规则结构化消费；
    - 补充②：文本层为空时整体切换为 parse_pdf_deep（扫描件场景）；
    - 互校：两侧数字集合差异记日志（关键数字只在 MinerU 侧出现 → 主路可能
      漏了表格内容，提示勾稽重点核对），不阻塞。
    """
    file_path = Path(path)
    if text_layer is None:
        from src.parsers.pdf_parser import PdfParser

        text_layer = PdfParser().parse(file_path)

    md = _engine_parse(file_path, tier)

    # 补充①：表格块（去重：文本层已含完全相同表格行的场景跳过）
    layer_text = "\n".join(b.text for b in text_layer.blocks)
    appended = 0
    for table in extract_table_blocks(md):
        if table not in layer_text:
            text_layer.blocks.append(
                TextBlock(text=table, page=None, paragraph=len(text_layer.blocks) + 1)
            )
            appended += 1

    # 互校对账（日志级）
    diff = cross_check_numbers(md, layer_text)
    if diff["mineru_only"]:
        logger.info(
            "MinerU 互校：%s 侧独有数字（主路可能漏表格内容，勾稽重点核对）: %s",
            "MinerU",
            diff["mineru_only"][:10],
        )
    logger.info(
        "MinerU 混合解析完成：%s 主路块 + %s 表格补充块",
        len(text_layer.blocks) - appended, appended,
    )
    return text_layer


def extract_table_blocks(markdown: str) -> list[str]:
    """供勾稽层消费：MinerU markdown 中的表格块列表。"""
    return _split_table_blocks(markdown)


def pdf_text_layer_empty(path: str | Path, min_chars_per_page: int = 20) -> bool:
    """探测 PDF 是否无有效文本层（扫描件）——路由到 MinerU 的判据之一。"""
    from pypdf import PdfReader

    with open(path, "rb") as fh:
        reader = PdfReader(fh)
        pages = len(reader.pages) or 1
        total = sum(len((p.extract_text() or "").strip()) for p in reader.pages)
    return total < min_chars_per_page * pages


class MinerUDeepParser(DocumentParser):
    """解析器形态包装（对齐 DocumentParser 接口）；路由由 document_service 控制。"""

    def __init__(self, tier: str = "standard"):
        self.tier = tier

    def parse(self, path: str | Path) -> ParsedDocument:
        return parse_pdf_deep(path, tier=self.tier)


def cross_check_numbers(mineru_md: str, text_layer: str) -> dict:
    """互校对账（日志级，不阻塞）：MinerU 侧与文本层的数字集合差异。

    返回 {"mineru_only": [...], "text_only": [...]}——MinerU-only 的关键
    数字若为利率/金额类，提示主路可能漏了表格内容（勾稽应重点核对）。
    """
    from src.services.tamper_check import NUM_RE, norm_number

    mine = {norm_number(n) for n in NUM_RE.findall(mineru_md or "")}
    layer = {norm_number(n) for n in NUM_RE.findall(text_layer or "")}
    mine.discard("")
    layer.discard("")
    return {
        "mineru_only": sorted(mine - layer)[:20],
        "text_only": sorted(layer - mine)[:20],
    }
