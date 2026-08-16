"""解析器工厂：按文件扩展名分发到对应解析器。"""

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock
from src.parsers.docx_parser import DocxParser
from src.parsers.ocr_parser import OcrParser
from src.parsers.pdf_parser import PdfParser
from src.parsers.txt_parser import TxtParser
from src.utils.errors import AppError, ErrorCode

_PARSERS: dict[str, DocumentParser] = {
    "pdf": PdfParser(),
    "doc": DocxParser(),
    "docx": DocxParser(),
    "txt": TxtParser(),
    "png": OcrParser(),
    "jpg": OcrParser(),
    "jpeg": OcrParser(),
    "bmp": OcrParser(),
}


def get_parser(filename: str) -> DocumentParser:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _PARSERS.get(ext)
    if parser is None:
        raise AppError(ErrorCode.FILE_TYPE_NOT_SUPPORTED, f"不支持的格式: .{ext}")
    return parser


def parse_document(path: str) -> ParsedDocument:
    """按扩展名解析文档。入口统一走此函数。"""
    parser = get_parser(path)
    return parser.parse(path)


__all__ = [
    "DocumentParser",
    "ParsedDocument",
    "TextBlock",
    "get_parser",
    "parse_document",
]
