"""OCR 解析器：RapidOCR（onnxruntime）识别图片文字，接入现有解析/脱敏/审查管线。

图片视为第 1 页，识别出的文字行合并为段落块。引擎惰性加载，测试可注入假引擎。
"""

from pathlib import Path

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock


class OcrParser(DocumentParser):
    def __init__(self, engine=None):
        self._engine = engine  # 测试注入；真实运行惰性加载 RapidOCR

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def parse(self, path: str | Path) -> ParsedDocument:
        result, _ = self._get_engine()(str(path))  # result: [[box, text, score], ...]
        blocks: list[TextBlock] = []
        for i, item in enumerate(result or [], start=1):
            text = str(item[1]).strip()
            if not text:
                continue
            blocks.append(TextBlock(text=text, page=1, paragraph=i))
        return ParsedDocument(file_name=Path(path).name, blocks=blocks)
