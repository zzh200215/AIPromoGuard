"""F2-3 结论生命周期时间线的纯函数测试（build_trail）。

事件语义：检出（或系统自动确认）→ 人工判定 → 翻案改判 → 撤销复核。
翻案判定依据 before_status 已是判定结果且被改判（与 R4-1 同口径）。
"""

import json
from datetime import datetime

from src.services.result_trail import (
    EVENT_AUTO_CONFIRMED,
    EVENT_CONFIRM,
    EVENT_DETECTED,
    EVENT_OVERTURN,
    EVENT_REVERT,
    build_trail,
)


class _FakeResult:
    def __init__(
        self,
        status="pending_confirm",
        confirmed_by=None,
        violation_type="rule",
        confidence=0.9,
    ):
        self.id = 1
        self.status = status
        self.confirmed_by = confirmed_by
        self.violation_type = violation_type
        self.confidence_score = confidence
        self.created_at = datetime(2026, 10, 5, 10, 0, 0)


class _FakeOp:
    def __init__(self, action, detail, username="合规张三", at=None):
        self.action = action
        self.detail = detail
        self.username = username
        self.created_at = at or datetime(2026, 10, 5, 11, 0, 0)


def test_detected_only_when_no_ops():
    events = build_trail(_FakeResult(), [])
    assert len(events) == 1
    assert events[0]["type"] == EVENT_DETECTED
    assert "规则引擎检出" in events[0]["detail"]
    assert "0.90" in events[0]["detail"]
    assert events[0]["actor"] == "系统"


def test_auto_confirmed_is_its_own_event_type():
    events = build_trail(_FakeResult(status="confirmed", confirmed_by=0), [])
    assert events[0]["type"] == EVENT_AUTO_CONFIRMED
    assert "自动确认" in events[0]["detail"]


def test_human_confirm_event():
    """pending → confirmed 是常规复核判定，不是翻案（状态与判定不同命名空间）。"""
    op = _FakeOp(
        "result.confirm",
        '{"before_status": "pending_confirm", "verdict": "confirmed"}',
    )
    events = build_trail(_FakeResult(), [op])
    assert len(events) == 2
    assert events[1]["type"] == EVENT_CONFIRM
    assert events[1]["actor"] == "合规张三"
    assert "判定为已确认违规" in events[1]["detail"]
    assert "原：待复核" in events[1]["detail"]


def test_pending_to_false_positive_is_confirm_not_overturn():
    """pending → false_positive 同样是常规复核（剔除误报），非翻案。"""
    op = _FakeOp(
        "result.confirm",
        '{"before_status": "pending_confirm", "verdict": "false_positive"}',
    )
    events = build_trail(_FakeResult(), [op])
    assert events[1]["type"] == EVENT_CONFIRM
    assert "判定为已剔除误报" in events[1]["detail"]


def test_overturn_detected_by_status_flip():
    """confirmed → false_positive = 翻案改判（不是普通判定）。"""
    op = _FakeOp(
        "result.confirm",
        json.dumps(
            {
                "before_status": "confirmed",
                "verdict": "false_positive",
                "before_auto_confirmed": True,
            }
        ),
    )
    events = build_trail(_FakeResult(status="false_positive", confirmed_by=7), [op])
    assert events[1]["type"] == EVENT_OVERTURN
    assert "翻案改判" in events[1]["detail"]
    assert "纠错对象为系统自动确认" in events[1]["detail"]


def test_revert_event():
    op = _FakeOp("result.revert", '{"before_status": "confirmed", "bulk": true}')
    events = build_trail(_FakeResult(), [op])
    assert events[1]["type"] == EVENT_REVERT
    assert "撤销复核" in events[1]["detail"]
    assert "批量操作" in events[1]["detail"]


def test_bulk_confirm_marked():
    op = _FakeOp(
        "result.confirm",
        '{"before_status": "pending_confirm", "verdict": "false_positive", "bulk": true}',
    )
    events = build_trail(_FakeResult(), [op])
    assert events[1]["type"] == EVENT_CONFIRM
    assert "批量操作" in events[1]["detail"]


def test_pending_to_same_verdict_after_revert_is_confirm():
    """撤销后重新判定（pending → confirmed）仍是常规复核，不是翻案。"""
    ops = [
        _FakeOp("result.revert", '{"before_status": "confirmed", "bulk": false}'),
        _FakeOp("result.confirm", '{"before_status": "pending_confirm", "verdict": "confirmed"}'),
    ]
    events = build_trail(_FakeResult(), ops)
    assert [e["type"] for e in events] == [EVENT_DETECTED, EVENT_REVERT, EVENT_CONFIRM]


def test_corrupt_detail_degrades_gracefully():
    """坏 detail（非 JSON）不炸，退化为无 before/verdict 的判定事件。"""
    op = _FakeOp("result.confirm", "not-json")
    events = build_trail(_FakeResult(), [op])
    assert len(events) == 2
    assert events[1]["type"] == EVENT_CONFIRM


def test_multiple_ops_ordered():
    ops = [
        _FakeOp("result.confirm", '{"before_status": "pending_confirm", "verdict": "confirmed"}'),
        _FakeOp(
            "result.confirm",
            '{"before_status": "confirmed", "verdict": "false_positive"}',
            username="复核李四",
        ),
    ]
    events = build_trail(_FakeResult(), ops)
    assert [e["type"] for e in events] == [EVENT_DETECTED, EVENT_CONFIRM, EVENT_OVERTURN]
    assert events[2]["actor"] == "复核李四"
