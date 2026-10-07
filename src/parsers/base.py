"""文档解析基类与解析结果数据结构。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TextBlock:
    """带原文位置信息的文本块（通常对应一个段落）。"""

    text: str
    page: int | None = None      # 页码，1 起；docx 等无分页信息时为 None
    paragraph: int | None = None  # 文档内段落序号，1 起
    heading: bool = False           # 是否为标题（docx 按样式识别）


@dataclass
class ParsedDocument:
    """解析后的完整文档。"""

    file_name: str
    blocks: list[TextBlock] = field(default_factory=list)
    title: str = ""
    domain: str | None = None    # 由 DocClassifier 填充（W2）
    doc_type: str | None = None  # 说明书/协议/宣传材料
    # 方案 A：解析脱敏时采集的敏感命中元数据（[{"kind":..., "value":...}]），
    # 供下游检测层使用——脱敏后文本已无法用正则扫出 PII
    mask_spans: list[dict] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


class DocumentParser(ABC):
    """解析器接口：输入文件路径，输出带位置信息的 ParsedDocument。"""

    @abstractmethod
    def parse(self, path: str | Path) -> ParsedDocument:
        ...
