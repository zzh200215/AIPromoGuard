from src.parsers.base import TextBlock
from src.parsers.chunker import chunk_blocks


def _blocks(n: int, text_len: int = 90) -> list[TextBlock]:
    return [
        TextBlock(text=f"第{i}段" + "x" * text_len, page=(i - 1) // 10 + 1, paragraph=i)
        for i in range(1, n + 1)
    ]


def _h(text: str, paragraph: int) -> TextBlock:
    return TextBlock(text=text, page=1, paragraph=paragraph, heading=True)


def _p(text: str, paragraph: int) -> TextBlock:
    return TextBlock(text=text, page=1, paragraph=paragraph, heading=False)


def test_chunk_preserves_location():
    chunks = chunk_blocks(_blocks(25), chunk_size=300, overlap=30)
    assert len(chunks) > 5
    starts = [c.paragraph_start for c in chunks]
    assert starts == sorted(starts)
    assert chunks[0].start_page == 1


def test_chunk_overlap_continuity():
    chunks = chunk_blocks(_blocks(9, text_len=80), chunk_size=250, overlap=30)
    assert len(chunks) >= 2
    for i in range(1, len(chunks)):
        assert chunks[i].paragraph_start <= chunks[i - 1].paragraph_end


def test_chunk_single_long_block():
    chunks = chunk_blocks(_blocks(1, text_len=2000), chunk_size=300, overlap=50)
    assert len(chunks) == 1
    assert chunks[0].paragraph_start == 1
    assert "第1段" in chunks[0].text


# ---------- 方向④ 语义切块：标题边界 ----------

def test_heading_starts_new_chunk():
    """标题是章节边界：标题前内容先独立成块，标题从新 chunk 开头、不被埋中间。"""
    chunks = chunk_blocks(
        [_p("起息日说明" * 10, 1), _h("风险提示", 2), _p("产品不保本" * 10, 3)],
        chunk_size=500, overlap=30,
    )
    assert len(chunks) == 2
    assert "风险提示" not in chunks[0].text          # 标题不被埋在上一块
    assert chunks[1].text.startswith("风险提示")       # 标题一定在 chunk 开头


def test_heading_at_doc_head_anchors_section():
    """文档开头标题与其章节正文同块，不产生空头块。"""
    chunks = chunk_blocks(
        [_h("产品亮点", 1), _p("业绩比较基准" * 10, 2)],
        chunk_size=500, overlap=30,
    )
    assert len(chunks) == 1
    assert chunks[0].text.startswith("产品亮点")


def test_no_overlap_carried_across_heading():
    """标题处是干净语义边界：上一节正文不通过 overlap 混进标题块。"""
    chunks = chunk_blocks(
        [_p("甲" * 120, 1), _p("乙" * 120, 2), _p("丙" * 120, 3),
         _h("风险提示", 4), _p("丁" * 120, 5)],
        chunk_size=300, overlap=100,
    )
    # 找到标题所在 chunk，断言其内容不含上一节的片段（不跨标题携带 overlap）
    h_chunk = next(c for c in chunks if c.text.startswith("风险提示"))
    assert "甲" not in h_chunk.text
    assert "乙" not in h_chunk.text
    assert "丙" not in h_chunk.text


def test_respect_headings_false_preserves_legacy():
    """关闭标题感知（respect_headings=False）→ 标题退回普通段落，行为不变。"""
    blocks = [_p("甲" * 110, 1), _h("风险提示", 2), _p("乙" * 110, 3)]
    on = chunk_blocks(blocks, chunk_size=300, overlap=0, respect_headings=True)
    off = chunk_blocks(blocks, chunk_size=300, overlap=0, respect_headings=False)
    assert len(off) == 1          # 标题内嵌同块
    assert len(on) == 2           # 标题强制分块
    assert "风险提示" in off[0].text
