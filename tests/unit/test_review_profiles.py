"""审查策略 profile 测试：归一/降级、HIL 覆盖、自动确认分流、报告呈现、DB 字段。"""

import pytest
import src.core.agents.nodes.human_review as hr
from sqlalchemy import text
from src.core.profiles import (
    effective_auto_confirm,
    normalize_profile,
    resolve_human_review,
    safe_profile,
)
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown
from src.services.review_service import _auto_confirm

# ---------- 归一 / 容错 ----------


def test_normalize_profile():
    assert normalize_profile(None) is None
    assert normalize_profile("") is None
    assert normalize_profile("  STRICT ") == "strict"
    with pytest.raises(ValueError):
        normalize_profile("bogus")


def test_safe_profile_degrades_to_standard():
    assert safe_profile("LOOSE") == "loose"
    assert safe_profile("bogus") is None
    assert safe_profile(None) is None


# ---------- HIL 关卡覆盖 ----------


def test_resolve_human_review_matrix():
    assert resolve_human_review("strict", config_enabled=False) is True
    assert resolve_human_review("loose", config_enabled=True) is False
    assert resolve_human_review("standard", config_enabled=True) is True
    assert resolve_human_review(None, config_enabled=False) is False


# ---------- 自动确认分流 ----------


def test_effective_auto_confirm_matrix():
    base = {"enabled": True, "threshold": 0.85}
    assert effective_auto_confirm("strict", base)["enabled"] is False
    loose = effective_auto_confirm("loose", base)
    assert loose["enabled"] is True and loose["threshold"] == 0.6
    assert effective_auto_confirm("standard", base) is base  # 原样跟随全局
    assert effective_auto_confirm(None, base) is base


def test_auto_confirm_strict_all_pending():
    """strict：高置信 hybrid 也不自动确认，全部进人工队列。"""
    cfg = effective_auto_confirm("strict", {"enabled": True, "threshold": 0.85})
    status, _, _ = _auto_confirm(
        {"violation_type": "hybrid", "confidence": 0.99}, cfg
    )
    assert status == "pending_confirm"


def test_auto_confirm_loose_lower_threshold():
    """loose：阈值 0.85→0.6，中高置信 hybrid 自动确认，过低的仍进队列。"""
    cfg = effective_auto_confirm("loose", {"enabled": True, "threshold": 0.85})
    confirmed, _, _ = _auto_confirm({"violation_type": "hybrid", "confidence": 0.7}, cfg)
    assert confirmed == "confirmed"
    pending, _, _ = _auto_confirm({"violation_type": "hybrid", "confidence": 0.5}, cfg)
    assert pending == "pending_confirm"


# ---------- human_review 节点 profile 覆盖 ----------


def _cfg(enabled: bool):
    from types import SimpleNamespace

    return SimpleNamespace(
        app_config=lambda section: {
            "human_review": {
                "enabled": enabled,
                "review_severities": ["high"],
                "review_sources": ["hybrid"],
            }
        }
    )


def _finding(source="rule", severity="medium", description="测试结论"):
    return {"source": source, "severity": severity, "description": description}


def test_node_strict_forces_full_review(monkeypatch):
    """strict：全局关闭也拦截，且全部结论进入待复核清单（不限 severity/source）。"""
    monkeypatch.setattr(hr, "settings", _cfg(enabled=False))
    findings = [_finding(severity="low"), _finding(source="llm"), _finding()]
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"rejected_indexes": [0]}

    monkeypatch.setattr(hr, "interrupt", fake_interrupt)
    result = hr.human_review({"merged_findings": findings, "profile": "strict"})
    assert len(captured["payload"]) == 3
    assert result["human_review"]["required"] is True
    assert result["human_review"]["rejected_indexes"] == [0]
    assert len(result["merged_findings"]) == 2


def test_node_strict_empty_findings_passthrough(monkeypatch):
    monkeypatch.setattr(hr, "settings", _cfg(enabled=False))
    result = hr.human_review({"merged_findings": [], "profile": "strict"})
    assert result == {"human_review": {"required": False, "rejected_indexes": []}}


def test_node_loose_passthrough_despite_config(monkeypatch):
    """loose：全局开启也直通，不打扰预检流程。"""
    monkeypatch.setattr(hr, "settings", _cfg(enabled=True))
    findings = [_finding(severity="high", source="hybrid")]
    assert hr.human_review({"merged_findings": findings, "profile": "loose"}) == {}


# ---------- 报告呈现 ----------


def test_report_markdown_profile_header():
    report = build_report(1, "d.docx", "banking", [], profile="strict")
    assert report["profile"] == "strict"
    md = render_markdown(report)
    assert "审查策略" in md and "对外投放" in md


def test_markdown_no_profile_line_by_default():
    md = render_markdown(build_report(1, "d.docx", None, []))
    assert "审查策略" not in md


# ---------- DB 字段（需本地 MySQL；列由迁移脚本/create_all 提供） ----------


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_tasks_profile_column():
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    rows = db.execute(text("SHOW COLUMNS FROM review_tasks LIKE 'profile'")).fetchall()
    db.close()
    assert len(rows) == 1
