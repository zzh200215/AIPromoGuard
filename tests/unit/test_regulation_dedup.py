"""法规级去重（per-regulation cap）单测。

背景：Top-K 名额常被同一部法规的多条近似条款占满。实测一场理财直播材料召回
5 条里有 3 条来自同一部办法，而对口的《金融产品网络营销管理办法》排第 6 进不来。
`_cap_per_regulation` 按法规限流，保证召回覆盖多部法规。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.regulation_service import _cap_per_regulation  # noqa: E402


def _items(pairs):
    return [{"regulation_name": n, "article_no": f"第{i}条", "score": 1 - i * 0.01}
            for i, (n,) in enumerate(pairs)]


def test_cap_zero_is_noop():
    items = _items([("A",), ("A",), ("B",)])
    assert _cap_per_regulation(items, 0) == items


def test_cap_one_keeps_one_per_regulation():
    items = _items([("A",), ("A",), ("A",), ("B",), ("C",)])
    got = [x["regulation_name"] for x in _cap_per_regulation(items, 1)]
    assert got == ["A", "B", "C"]


def test_cap_two_allows_two_per_regulation():
    items = _items([("A",), ("A",), ("A",), ("B",)])
    got = [x["regulation_name"] for x in _cap_per_regulation(items, 2)]
    assert got == ["A", "A", "B"]


def test_cap_preserves_original_order_within_quota():
    items = _items([("A",), ("B",), ("A",), ("C",)])
    capped = _cap_per_regulation(items, 1)
    assert [x["regulation_name"] for x in capped] == ["A", "B", "C"]
    # 保留的是靠前的那条（第一条 A，而不是第三条 A）
    assert capped[0]["article_no"] == "第0条"


def test_cap_handles_missing_regulation_name():
    items = [{"article_no": "第一条"}, {"regulation_name": "", "article_no": "第二条"}]
    got = _cap_per_regulation(items, 1)
    assert len(got) == 1  # 空名归为同一"法规"，只留一条
