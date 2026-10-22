"""PBC 法规抓取器的纯函数（标题清洗 / 生效日期解析）。

抓取本身依赖外网，不做联网单测；这里只锁解析口径，防止标题或日期被悄悄改坏。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "crawl"))

from fetch_pbc_regulations import _clean_title, _effective_date  # noqa: E402


def test_clean_title_extracts_inner_name():
    title = "中国人民银行令〔2026〕第3号（中国人民银行行政复议办法）"
    assert _clean_title(title) == "中国人民银行行政复议办法"


def test_clean_title_strips_ling_prefix_without_inner():
    title = "中国人民银行令〔2026〕第1号"
    assert _clean_title(title) == "〔2026〕第1号"


def test_effective_date_parsed():
    body = "……现予发布，自2026年3月1日起施行。"
    assert _effective_date(body) == "2026-03-01"


def test_effective_date_missing_returns_none():
    assert _effective_date("本办法自发布之日起施行") is None
