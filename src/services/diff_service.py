"""版本对比 diff 服务：按文本块序列比对产出变更片段，并构造定向复审输入。

MVP 用标准库 difflib.SequenceMatcher（对 blocks 序列做块级比对，中文无需分词）。
定向复审只审"变更块 + 上下文窗口"，不全文重审。
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

from src.parsers.base import TextBlock


@dataclass
class DiffChange:
    change_type: str                       # added / removed / modified
    change_id: str                         # c1, c2, ...
    old_text: str = ""
    new_text: str = ""
    block_index: int | None = None         # 变更片段在新文档 blocks 中的起始索引；removed 为 None
    block_count: int = 0                   # 涉及新文档 blocks 数量（added/modified）

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type,
            "change_id": self.change_id,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "block_index": self.block_index,
            "block_count": self.block_count,
        }


def diff_documents(
    old_blocks: list[dict | TextBlock], new_blocks: list[dict | TextBlock]
) -> list[DiffChange]:
    """对两个文档的文本块序列做块级比对，返回变更片段列表（保持新文档顺序）。"""
    old_texts = [b["text"] if isinstance(b, dict) else b.text for b in old_blocks]
    new_texts = [b["text"] if isinstance(b, dict) else b.text for b in new_blocks]

    matcher = SequenceMatcher(None, old_texts, new_texts, autojunk=False)
    changes: list[DiffChange] = []
    idx = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        idx += 1
        change_id = f"c{idx}"
        if tag == "replace":
            changes.append(
                DiffChange(
                    change_type="modified",
                    change_id=change_id,
                    old_text="\n".join(old_texts[i1:i2]),
                    new_text="\n".join(new_texts[j1:j2]),
                    block_index=j1,
                    block_count=j2 - j1,
                )
            )
        elif tag == "delete":
            changes.append(
                DiffChange(
                    change_type="removed",
                    change_id=change_id,
                    old_text="\n".join(old_texts[i1:i2]),
                    block_index=None,
                    block_count=0,
                )
            )
        else:  # insert
            changes.append(
                DiffChange(
                    change_type="added",
                    change_id=change_id,
                    new_text="\n".join(new_texts[j1:j2]),
                    block_index=j1,
                    block_count=j2 - j1,
                )
            )
    return changes


def build_review_blocks(
    new_blocks: list[dict | TextBlock],
    changes: list[DiffChange],
    context_blocks: int = 2,
) -> list[dict]:
    """定向复审输入 = 变更片段涉及的新文档块 + 前后 context 块，去重保序返回。"""
    indexes: set[int] = set()
    for c in changes:
        if c.block_index is None:
            continue  # removed 无新位置，不参与复审
        start = max(0, c.block_index - context_blocks)
        end = min(len(new_blocks), c.block_index + c.block_count + context_blocks)
        indexes.update(range(start, end))

    def _to_dict(b):
        if isinstance(b, dict):
            return b
        return {
            "text": b.text,
            "page": b.page,
            "paragraph": b.paragraph,
            "heading": b.heading,
        }

    return [_to_dict(new_blocks[i]) for i in sorted(indexes)]
