"""证监规章抓取的纯函数护栏（不联网）。

- `_csrc_web_text`：网页正文兜底时不能把页头"下载图片版/下载文字版"带进条款正文
- `_safe_filename`：法规名里带 <> 时，Windows 写盘会 PermissionError
"""

import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "crawl"))

from fetch_regulations import _csrc_web_text, _safe_filename  # noqa: E402


def _soup(html: str):
    return BeautifulSoup(html, "lxml")


def test_csrc_web_text_strips_page_noise():
    """页头噪声行（独立成行）必须被剥掉，正文首行仍是条款。"""
    paras = "<p>中国证券监督管理委员会规章</p><p>下载图片版</p><p>下载文字版</p>"
    body = "".join(f"<p>第{i}条 为了规范上市公司信息披露行为，制定本办法。</p>" for i in range(1, 40))
    text = _csrc_web_text(_soup(f"<div>{paras}{body}</div>"))
    assert "下载文字版" not in text
    assert "中国证券监督管理委员会规章" not in text
    assert text.splitlines()[0].startswith("第1条")


def test_csrc_web_text_prefers_block_with_most_articles():
    """多个候选块时，应选条款密度最高的那块（而不是最长或最先出现）。"""
    short = "<div>" + "".join(f"<p>第{i}条 内容。</p>" for i in range(1, 3)) + "</div>"
    dense = "<div>" + "".join(
        f"<p>第{i}条 这里是条款正文内容，用于测试块选择。</p>" for i in range(1, 40)
    ) + "</div>"
    filler = "<div>" + "<p>无关的说明文字，没有条款锚点。</p>" * 80 + "</div>"
    text = _csrc_web_text(_soup(short + filler + dense))
    assert "第39条" in text
    assert "无关的说明文字" not in text


def test_safe_filename_replaces_windows_illegal_chars():
    assert _safe_filename("关于修改<非上市公众公司监督管理办法>的决定") == (
        "关于修改_非上市公众公司监督管理办法_的决定"
    )
    assert _safe_filename('a/b\\c:d*e?f"g|h') == "a_b_c_d_e_f_g_h"


def test_safe_filename_keeps_normal_chinese():
    assert _safe_filename("个人住房贷款管理办法（试行）") == "个人住房贷款管理办法（试行）"
