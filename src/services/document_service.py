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
        """解析路由：普通文档走工厂；PDF 按条件切 MinerU 混合通道，否则走表格补充.

        路由（PR-5 后）：
        - 非 PDF：解析工厂直出；
        - PDF + MinerU 关闭（默认）：pypdf 文本层主路 + pdfplumber 表格补充
          （只补不替，见 _parse_text_layer）；
        - PDF + MinerU 开启：扫描件走深解析（文本层为空）或混合解析
          （mineru_always）；MinerU 未安装/失败时降级回"文本层 + 表格补充"。
        """
        cfg = settings.app_config("parser")
        path_str = str(file_path)
        is_pdf = path_str.lower().endswith(".pdf")
        if not is_pdf:
            return parse_document(path_str)
        if not cfg.get("mineru_enabled"):
            return self._parse_text_layer(path_str, cfg)

        from src.parsers.mineru_parser import parse_pdf_hybrid, pdf_text_layer_empty

        try:
            scan_like = pdf_text_layer_empty(path_str)
        except Exception as exc:  # noqa: BLE001 — 加密/损坏 PDF 交还原路报错
            logger.warning("PDF 文本层探测失败，走原路: %s", exc)
            return self._parse_text_layer(path_str, cfg)

        if not scan_like and not cfg.get("mineru_always"):
            return self._parse_text_layer(path_str, cfg)

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
            return self._parse_text_layer(path_str, cfg)

    def _parse_text_layer(self, path_str: str, cfg: dict) -> ParsedDocument:
        """文字版 PDF 主路：pypdf 文本层（页码/封面文本块完整）+ 表格补充（PR-5）.

        表格补充（pdfplumber 通道）**只增不改**——pypdf 块一个不动，markdown
        表格块追加在尾部供勾稽规则消费；pdfplumber 不可用/异常/未开启时
        静默走纯文本层（记日志）。扫描件（文本层为空）由 parse_document 维持
        422 语义，不受本补充影响。
        """
        doc = parse_document(path_str)
        if cfg.get("pdf_tables_enabled", True):
            from src.parsers.pdf_table_adapter import merge_pdf_tables

            merge_pdf_tables(doc, path_str)
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
        # 方向④语义切块：按标题边界优先断开（configs/app.yaml parser.chunk_respect_headings）
        respect_headings = bool(parser_cfg.get("chunk_respect_headings", True))
        return chunk_blocks(
            doc.blocks, chunk_size=size, overlap=ov, respect_headings=respect_headings
        )


document_service = DocumentService()
