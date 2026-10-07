"""TXT 解析器：兼容 utf-8 / gbk 编码，按换行切分段落。

方向④：识别 Markdown ATX 标题（行首 `#`），标记 heading=True 供语义切块
把标题当作章节边界（docx 走样式识别，txt 走此保守识别，避免误判正文）。
"""

import re
from pathlib import Path

from src.parsers.base import DocumentParser, ParsedDocument, TextBlock

_ATX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


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
            m = _ATX_HEADING.match(line)
            if m:
                # Markdown 标题：去掉 # 标记，标记为标题块
                blocks.append(
                    TextBlock(text=m.group(1).strip(), page=1, paragraph=idx, heading=True)
                )
            else:
                blocks.append(TextBlock(text=line, page=1, paragraph=idx))

        return ParsedDocument(
            file_name=file_path.name,
            title=blocks[0].text if blocks else "",
            blocks=blocks,
        )
