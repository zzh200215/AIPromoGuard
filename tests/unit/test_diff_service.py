"""diff 服务测试：相同→空、纯新增/删除/修改、上下文窗口。"""

from src.parsers.base import TextBlock
from src.services.diff_service import build_review_blocks, diff_documents


def _blocks(texts):
    return [{"text": t, "page": 1, "paragraph": i + 1} for i, t in enumerate(texts)]


def test_identical_documents_no_changes():
    b = _blocks(["甲", "乙", "丙"])
    assert diff_documents(b, _blocks(["甲", "乙", "丙"])) == []


def test_pure_addition():
    old = _blocks(["甲", "乙"])
    new = _blocks(["甲", "乙", "丙", "丁"])
    changes = diff_documents(old, new)
    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "added"
    assert c.new_text == "丙\n丁"
    assert c.block_index == 2
    assert c.block_count == 2


def test_pure_removal():
    old = _blocks(["甲", "乙", "丙"])
    new = _blocks(["甲", "丙"])
    changes = diff_documents(old, new)
    assert len(changes) == 1
    assert changes[0].change_type == "removed"
    assert changes[0].new_text == ""
    assert changes[0].block_index is None


def test_modified_block():
    old = _blocks(["甲", "乙", "丙"])
    new = _blocks(["甲", "改后的乙", "丙"])
    changes = diff_documents(old, new)
    assert len(changes) == 1
    assert changes[0].change_type == "modified"
    assert changes[0].old_text == "乙"
    assert changes[0].new_text == "改后的乙"
    assert changes[0].block_index == 1


def test_build_review_blocks_with_context():
    new = _blocks(["a", "b", "c", "d", "e"])
    # 变更在 index 2（"c"，纯新增 "c","d","e"），context=2 → 覆盖 index 0..4 全部
    changes = [c for c in diff_documents(_blocks(["a", "b"]), new) if c.change_type == "added"]
    assert len(changes) == 1
    assert changes[0].block_index == 2
    assert changes[0].block_count == 3
    blocks = build_review_blocks(new, changes, context_blocks=2)
    assert [b["paragraph"] for b in blocks] == [1, 2, 3, 4, 5]


def test_change_ids_are_sequential():
    old = _blocks(["甲", "乙", "丙", "丁"])
    new = _blocks(["甲", "改", "丙", "戊"])
    changes = diff_documents(old, new)
    assert [c.change_id for c in changes] == ["c1", "c2"]


def test_accepts_textblock_objects():
    old = [TextBlock(text="甲", page=1, paragraph=1)]
    new = [TextBlock(text="甲", page=1, paragraph=1), TextBlock(text="新增", page=1, paragraph=2)]
    changes = diff_documents(old, new)
    assert len(changes) == 1
    assert changes[0].change_type == "added"
    blocks = build_review_blocks(new, changes, context_blocks=2)
    assert [b["text"] for b in blocks] == ["甲", "新增"]
