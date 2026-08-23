"""PDF 解析器：基于 pypdf 按页提取文本，按页内空行切分段落，保留页码。"""

from pathlib import Path

from pypdf import PdfReader

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock
from src.utils.errors import AppError, ErrorCode


def _split_paragraphs(page_text: str) -> list[str]:
    """把单页提取的文本切成段落：优先按空行，其次按换行。"""
    parts = [p.strip() for p in page_text.split("\n\n")]
    if any(parts):
        return [p for p in parts if p]
    return [p for p in (line.strip() for line in page_text.splitlines()) if p]


class PdfParser(DocumentParser):
    def parse(self, path: str | Path) -> ParsedDocument:
        file_path = Path(path)
        # with 保证文件句柄释放（pypdf 不会自动关，Windows 上会锁住文件）
        with open(file_path, "rb") as fh:
            reader = PdfReader(fh)
            blocks: list[TextBlock] = []
            paragraph_no = 0
            for page_idx in range(len(reader.pages)):
                page_text = reader.pages[page_idx].extract_text() or ""
                for para in _split_paragraphs(page_text):
                    paragraph_no += 1
                    blocks.append(
                        TextBlock(text=para, page=page_idx + 1, paragraph=paragraph_no)
                    )
        if not blocks:
            # 扫描版/图片型 PDF 提取不到文本：静默返回空会让审查"零违规"通过，
            # 合规场景属高危漏检，必须显式失败并给出可操作提示
            raise AppError(
                ErrorCode.FILE_TYPE_NOT_SUPPORTED,
                "PDF 未提取到文本（疑似扫描版），请上传文字版 PDF，或导出为图片上传走 OCR",
                http_status=422,
            )
        return ParsedDocument(
            file_name=file_path.name,
            title=blocks[0].text if blocks else "",
            blocks=blocks,
        )
