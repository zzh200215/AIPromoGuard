"""文档分块：将段落合并为 chunk，保留位置范围（供向量化与 LLM 审查使用）。"""

from dataclasses import dataclass

from src.parsers.base import TextBlock


@dataclass
class Chunk:
    text: str
    start_page: int | None = None
    end_page: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    blocks: list[TextBlock] | None = None


def _tail_blocks(blocks: list[TextBlock], overlap: int) -> list[TextBlock]:
    """从尾部取出总长度不超过 overlap 的若干块，用于跨 chunk 重叠。"""
    if overlap <= 0:
        return []
    tail: list[TextBlock] = []
    total = 0
    for block in reversed(blocks):
        if total + len(block.text) > overlap and tail:
            break
        tail.append(block)
        total += len(block.text)
    return list(reversed(tail))


def _make_chunk(blocks: list[TextBlock]) -> Chunk:
    pages = [b.page for b in blocks if b.page is not None]
    paragraphs = [b.paragraph for b in blocks if b.paragraph is not None]
    return Chunk(
        text="\n".join(b.text for b in blocks),
        start_page=min(pages) if pages else None,
        end_page=max(pages) if pages else None,
        paragraph_start=min(paragraphs) if paragraphs else None,
        paragraph_end=max(paragraphs) if paragraphs else None,
        blocks=blocks,
    )


def chunk_blocks(
    blocks: list[TextBlock],
    chunk_size: int = 500,
    overlap: int = 50,
    respect_headings: bool = True,
) -> list[Chunk]:
    """按字符数合并段落为 chunk，优先在标题/段落边界断开；单段超长独立成 chunk。

    方向④语义切块（respect_headings=True）：
    - 标题（TextBlock.heading）是章节边界——标题一定从一个新 chunk 开头，
      不被埋在 chunk 中间、也不被 overlap 吞掉；
    - 标题处是干净语义边界，跨标题不携带 overlap（不同章节内容不混拼）；
    - 同章节内仍按溢出 + overlap 拼接，防「一条违规恰好被切缝劈两半」；
    - 段落永不截断（超长单段独立成 chunk，保证段落完整）。
    """
    chunks: list[Chunk] = []
    current: list[TextBlock] = []
    current_len = 0

    for block in blocks:
        if len(block.text) > chunk_size:
            if current:
                chunks.append(_make_chunk(current))
                current, current_len = [], 0
            chunks.append(_make_chunk([block]))
            continue
        if respect_headings and block.heading and current:
            # 标题处断开：之前内容直接成块、不带 overlap（干净章节边界）
            chunks.append(_make_chunk(current))
            current, current_len = [], 0
        if current_len + len(block.text) > chunk_size and current:
            chunks.append(_make_chunk(current))
            current = _tail_blocks(current, overlap)
            current_len = sum(len(b.text) for b in current)
        current.append(block)
        current_len += len(block.text)

    if current:
        chunks.append(_make_chunk(current))
    return chunks
