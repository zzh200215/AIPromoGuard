"""TXT 解析器：兼容 utf-8 / gbk 编码，按换行切分段落。"""

from pathlib import Path

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock


class TxtParser(DocumentParser):
    def parse(self, path: str | Path) -> ParsedDocument:
        file_path = Path(path)
        raw = file_path.read_bytes()
        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

        blocks: list[TextBlock] = []
        for idx, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            blocks.append(TextBlock(text=line, page=1, paragraph=idx))

        return ParsedDocument(
            file_name=file_path.name,
            title=blocks[0].text if blocks else "",
            blocks=blocks,
        )
