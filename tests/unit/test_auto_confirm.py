"""方向②人审分流测试：三档置信度自动确认。

- _auto_confirm 纯逻辑（不依赖 DB）：rule/hybrid 高置信自动 confirmed（confirmed_by=0），
  纯 llm 一律进人工队列，开关/阈值边界。
- _persist_results DB 集成（skipif）：写库后库内 status/confirmed_by/confirmed_at 正确。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewResult
from src.services import review_service
from src.services.review_service import _AUTO_CONFIRM_BY, _auto_confirm

_CFG = {"enabled": True, "threshold": 0.85}


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


# ---------- _auto_confirm 纯逻辑 ----------

def test_auto_confirm_rule_high_confidence():
    status, confirmed_at, confirmed_by = _auto_confirm(
        {"violation_type": "rule", "confidence": 0.95}, _CFG
    )
    assert status == "confirmed"
    assert isinstance(confirmed_at, datetime)
    assert confirmed_by == _AUTO_CONFIRM_BY


def test_auto_confirm_hybrid_qualified():
    status, _, confirmed_by = _auto_confirm(
        {"violation_type": "hybrid", "confidence": 0.9}, _CFG
    )
    assert status == "confirmed"
    assert confirmed_by == _AUTO_CONFIRM_BY


def test_auto_confirm_llm_always_manual():
    """纯 LLM 即使置信度很高也一律进人工队列。"""
    status, confirmed_at, confirmed_by = _auto_confirm(
        {"violation_type": "llm", "confidence": 0.99}, _CFG
    )
    assert status == "pending_confirm"
    assert confirmed_at is None
    assert confirmed_by is None


def test_auto_confirm_disabled_all_manual():
    status, confirmed_at, confirmed_by = _auto_confirm(
        {"violation_type": "rule", "confidence": 0.95}, {"enabled": False}
    )
    assert status == "pending_confirm"
    assert confirmed_at is None and confirmed_by is None


def test_auto_confirm_threshold_boundary():
    """阈值边界：confidence == threshold 自动过，低一点进人工。"""
    near = {"violation_type": "rule", "confidence": 0.849}
    at = {"violation_type": "rule", "confidence": 0.85}
    assert _auto_confirm(near, _CFG)[0] == "pending_confirm"
    assert _auto_confirm(at, _CFG)[0] == "confirmed"


def test_auto_confirm_hybrid_below_threshold_manual():
    status, _, _ = _auto_confirm({"violation_type": "hybrid", "confidence": 0.6}, _CFG)
    assert status == "pending_confirm"


def test_auto_confirm_missing_cfg_defaults_on():
    """未配置 auto_confirm 段时按默认开启（enabled=true, threshold=0.85）。"""
    status, _, _ = _auto_confirm({"violation_type": "rule", "confidence": 0.9}, {})
    assert status == "confirmed"


def test_auto_confirm_default_source_rule():
    """violation_type 缺失时按 rule 处理（与 conflict_resolve 输出一致）。"""
    status, _, _ = _auto_confirm({"confidence": 0.9}, _CFG)
    assert status == "confirmed"


# ---------- _persist_results DB 集成 ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_persist_results_three_tier(monkeypatch):
    db = SessionLocal()
    task_id = 987654321
    try:
        monkeypatch.setattr(
            review_service,
            "settings",
            SimpleNamespace(
                app_config=lambda section: (
                    {"auto_confirm": _CFG} if section == "workflow" else {}
                )
            ),
        )
        findings = [
            {"violation_type": "rule", "risk_level": "high", "original_text": "保本保收益",
             "confidence": 0.95, "page": 1, "paragraph": 1},
            {"violation_type": "hybrid", "risk_level": "medium", "original_text": "零风险",
             "confidence": 0.9, "page": 1, "paragraph": 2},
            {"violation_type": "llm", "risk_level": "low", "original_text": "夸大宣传",
             "confidence": 0.6, "page": 1, "paragraph": 3},
        ]
        review_service._persist_results(db, task_id, findings)
        db.commit()

        rows = (
            db.query(ReviewResult)
            .filter(ReviewResult.task_id == task_id)
            .order_by(ReviewResult.location_paragraph.asc())
            .all()
        )
        assert [r.status for r in rows] == ["confirmed", "confirmed", "pending_confirm"]
        assert rows[0].confirmed_by == _AUTO_CONFIRM_BY
        assert rows[1].confirmed_by == _AUTO_CONFIRM_BY
        assert rows[2].confirmed_by is None and rows[2].confirmed_at is None
        assert rows[0].confirmed_at is not None
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == task_id).delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_persist_results_disabled_all_pending(monkeypatch):
    db = SessionLocal()
    task_id = 987654322
    try:
        monkeypatch.setattr(
            review_service,
            "settings",
            SimpleNamespace(
                app_config=lambda section: (
                    {"auto_confirm": {"enabled": False}} if section == "workflow" else {}
                )
            ),
        )
        findings = [
            {"violation_type": "rule", "risk_level": "high", "original_text": "保本保收益",
             "confidence": 0.95, "page": 1, "paragraph": 1},
        ]
        review_service._persist_results(db, task_id, findings)
        db.commit()
        row = db.query(ReviewResult).filter(ReviewResult.task_id == task_id).first()
        assert row.status == "pending_confirm"
        assert row.confirmed_by is None
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == task_id).delete()
        db.commit()
        db.close()
