"""文档解析服务：解析 → 脱敏 → 分块，供任务编排与向量化使用。"""

from pathlib import Path

from src.parsers import ParsedDocument, parse_document
from src.parsers.chunker import Chunk, chunk_blocks
from src.utils.config import settings
from src.utils.masking import mask_sensitive


class DocumentService:
    def parse(self, file_path: str | Path) -> ParsedDocument:
        doc = parse_document(str(file_path))
        # 解析阶段脱敏（PRD §13.2）：系统处理的是脱敏后文本
        if settings.app_config("parser").get("mask_sensitive", True):
            for block in doc.blocks:
                block.text = mask_sensitive(block.text)
        return doc

    def chunk(
        self,
        doc: ParsedDocument,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        parser_cfg = settings.app_config("parser")
        size = chunk_size or parser_cfg.get("chunk_size", 500)
        ov = overlap if overlap is not None else parser_cfg.get("chunk_overlap", 50)
        return chunk_blocks(doc.blocks, chunk_size=size, overlap=ov)


document_service = DocumentService()
