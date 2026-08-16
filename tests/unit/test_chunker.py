from src.parsers.base import TextBlock
from src.parsers.chunker import chunk_blocks


def _blocks(n: int, text_len: int = 90) -> list[TextBlock]:
    return [
        TextBlock(text=f"第{i}段" + "x" * text_len, page=(i - 1) // 10 + 1, paragraph=i)
        for i in range(1, n + 1)
    ]


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
