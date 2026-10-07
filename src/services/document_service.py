"""文档解析服务：解析 → 脱敏 → 分块，供任务编排与向量化使用。"""

from pathlib import Path

from src.parsers import ParsedDocument, parse_document
from src.parsers.chunker import Chunk, chunk_blocks
from src.utils.config import settings
from src.utils.logger import get_logger
from src.utils.masking import mask_sensitive_with_spans

logger = get_logger(__name__)


class DocumentService:
    def parse(self, file_path: str | Path, *, mask: bool = True) -> ParsedDocument:
        """解析文档。mask=False 时跳过脱敏（供巡检基线等"与线上原文比对"的场景）。

        为什么需要 mask=False：解析阶段脱敏（PRD §13.2）会把金额抹成 `***元`，
        若巡检基线用脱敏文本、而抓取的线上内容是原文，两侧口径不一致会对每个
        材料产生"数字缺失"假阳性 → 巡检永远判 changed。10-07 修复。
        """
        doc = self._parse_routed(file_path)
        if mask and settings.app_config("parser").get("mask_sensitive", True):
            for block in doc.blocks:
                block.text, spans = mask_sensitive_with_spans(block.text)
                # 方案 A：脱敏与检测共用一遍扫描——命中元数据留在文档上，
                # 供检测层消费（脱敏后文本无法再用正则扫出 PII）。
                # 补块位置，让报告能标注"第几页/段"。
                for span in spans:
                    span["page"] = block.page
                    span["paragraph"] = block.paragraph
                doc.mask_spans.extend(spans)
        return doc

    def _parse_routed(self, file_path: str | Path) -> ParsedDocument:
        """解析路由（R2-1）：普通文档走既有工厂；PDF 按条件切 MinerU 混合通道。

        条件（全部满足才走 MinerU，成本护栏——MinerU CPU ~0.2 页/s）：
        - parser.mineru_enabled 显式开启（默认 false）；
        - 扩展名为 pdf；
        - 文本层为空（扫描件，原 PdfParser 直接 422）或 mineru_always 开启。
        MinerU 未安装/解析失败时降级回原路（扫描件维持原 422 语义）。
        """
        cfg = settings.app_config("parser")
        path_str = str(file_path)
        if not cfg.get("mineru_enabled") or not path_str.lower().endswith(".pdf"):
            return parse_document(path_str)

        from src.parsers.mineru_parser import parse_pdf_hybrid, pdf_text_layer_empty

        try:
            scan_like = pdf_text_layer_empty(path_str)
        except Exception as exc:  # noqa: BLE001 — 加密/损坏 PDF 交还原路报错
            logger.warning("PDF 文本层探测失败，走原路: %s", exc)
            return parse_document(path_str)

        if not scan_like and not cfg.get("mineru_always"):
            return parse_document(path_str)

        try:
            tier = cfg.get("mineru_tier", "standard")
            if scan_like:
                from src.parsers.mineru_parser import parse_pdf_deep

                logger.info("扫描件 PDF 走 MinerU 深解析: %s", path_str)
                return parse_pdf_deep(path_str, tier=tier)
            logger.info("PDF 走 MinerU 混合解析（主路+表格补充）: %s", path_str)
            return parse_pdf_hybrid(path_str, tier=tier)
        except Exception as exc:  # noqa: BLE001 — MinerU 任何失败降级原路
            logger.warning("MinerU 解析失败，降级原路: %s", exc)
            return parse_document(path_str)

    def chunk(
        self,
        doc: ParsedDocument,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        parser_cfg = settings.app_config("parser")
        size = chunk_size or parser_cfg.get("chunk_size", 500)
        ov = overlap if overlap is not None else parser_cfg.get("chunk_overlap", 50)
        # 方向④语义切块：按标题边界优先断开（configs/app.yaml parser.chunk_respect_headings）
        respect_headings = bool(parser_cfg.get("chunk_respect_headings", True))
        return chunk_blocks(
            doc.blocks, chunk_size=size, overlap=ov, respect_headings=respect_headings
        )


document_service = DocumentService()
