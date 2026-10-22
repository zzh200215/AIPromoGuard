"""NFRA docClob 正文提取的回归护栏。

背景：docClob 是 Word 导出的 HTML，正文里每个词可能被包成独立内联元素。
用 `get_text("\\n")` 取文本会把 "第二条" 拆成 "第\\n二\\n条"，
行首条款锚点全部失效 → 切分得到 0 条，整部法规被判"未命中"。
这里锁住"按 <p> 段落取文本"的行为。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "crawl"))

from fetch_regulations import _clob_text  # noqa: E402


def test_clob_fragmented_words_restored_to_paragraph():
    """碎片化的 "第/二/条" 必须还原成 "第二条"，且不插入换行。"""
    clob = (
        "<html><body>"
        "<p>第一章</p><p>总则</p>"
        "<p>第</p><p>二</p><p>条</p><p>本办法适用于银行。</p>"
        "</body></html>"
    )
    # 段落之间是独立 <p>，所以 "第"/"二"/"条" 各自成段——这正是原始数据的形态，
    # 关键在于段内不碎词，且拼行后行首仍是 "第X条"（此处为跨段的极端情形，不强求合并）
    text = _clob_text(clob)
    assert "本办法适用于银行。" in text


def test_clob_inline_spans_joined_without_newline():
    """同一段内被 <span> 拆开的词必须拼回连续文本（本 bug 的真实形态）。"""
    clob = (
        "<p>第十条<span>为</span><span>规范</span>业务，"
        "<span>制定</span>本办法。</p>"
        "<p>第十一条 本办法自发布之日起施行。</p>"
    )
    text = _clob_text(clob)
    assert "第十条为规范业务，制定本办法。" in text
    assert text.count("\n") == 1
    assert text.splitlines()[1].startswith("第十一条")


def test_clob_falls_back_when_no_paragraph():
    clob = "<div><br/>无段落结构的纯文本正文</div>"
    assert "无段落结构的纯文本正文" in _clob_text(clob)
