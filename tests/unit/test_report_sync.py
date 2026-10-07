"""报告与人工结论同步测试（report_service）：合并、过期检测、回写。

- render_markdown 纯逻辑：人工结论段/人工列/结构化法规引用渲染；
- merge_human_decisions / refresh_report DB 集成（skipif，同 test_auto_confirm 口径）。
"""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from src.core.report.markdown import render_markdown
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewResult
from src.services.report_service import merge_human_decisions, refresh_report

# ---------- render_markdown 纯逻辑 ----------

def test_markdown_renders_human_review_and_regulations():
    report = {
        "task_id": 1,
        "document_name": "产品说明.docx",
        "domain": "banking",
        "generated_at": "2026-01-01T00:00:00",
        "summary": {"total_violations": 2, "high_risk": 1, "medium_risk": 1, "low_risk": 0},
        "violations": [
            {"risk_level": "high", "source": "rule", "human_status": "confirmed",
             "human_confirmed_by": 5, "original_text": "保本保收益"},
            {"risk_level": "medium", "source": "llm", "human_status": "false_positive",
             "human_confirmed_by": 5, "original_text": "稳赚不赔"},
        ],
        "human_review": {
            "pending_confirm": 0, "confirmed": 1, "false_positive": 1,
            "auto_confirmed": 0, "manual_reviewed": 2,
            "final_total": 1, "final_high": 1, "final_medium": 0, "final_low": 0,
            "last_confirmed_at": "2026-01-02T10:00:00",
        },
        "regulations": [
            {"id": 3, "regulation_name": "证券法", "regulation_no": "国主席令第X号"},
        ],
    }
    md = render_markdown(report)
    assert "人工复核：已确认 **1** 处、剔除误报 **1** 处" in md
    assert "最终确认违规 **1** 处（高 1 / 中 0 / 低 0）" in md
    assert "| 人工 |" in md
    assert "已确认（自动）" not in md  # 人工确认不标自动
    assert "《证券法》（国主席令第X号）" in md


def test_markdown_marks_auto_confirmed_and_defaults():
    report = {
        "task_id": 1, "document_name": "d", "generated_at": "2026-01-01T00:00:00",
        "summary": {"total_violations": 1, "high_risk": 0, "medium_risk": 0, "low_risk": 1},
        "violations": [
            {"risk_level": "low", "source": "rule", "human_status": "confirmed",
             "human_confirmed_by": 0, "original_text": "x"},
            {"risk_level": "low", "source": "rule", "original_text": "y"},
        ],
    }
    md = render_markdown(report)
    assert "已确认（自动）" in md
    # 无 human_review 块时不渲染人工结论段
    assert "人工复核：" not in md
    assert "最终确认违规" not in md


# ---------- DB 集成 ----------

def _db_ready() -> bool:
    try:
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


_TASK_ID = 987654331


def _seed_results(db):
    rows = [
        ReviewResult(
            task_id=_TASK_ID, violation_type="rule", risk_level="high",
            original_text="保本保收益", confidence_score=0.95, status="confirmed",
            confirmed_by=7,
        ),
        ReviewResult(
            task_id=_TASK_ID, violation_type="llm", risk_level="medium",
            original_text="零风险", confidence_score=0.6, status="false_positive",
            confirmed_by=7,
        ),
        ReviewResult(
            task_id=_TASK_ID, violation_type="rule", risk_level="low",
            original_text="宽松表述", confidence_score=0.9, status="confirmed",
            confirmed_by=0,
        ),
    ]
    db.add_all(rows)
    db.commit()
    return rows


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_merge_human_decisions_summary():
    db = SessionLocal()
    try:
        _seed_results(db)
        report = {"violations": [{"original_text": "a"}, {"original_text": "b"},
                                 {"original_text": "c"}]}
        merge_human_decisions(db, report, _TASK_ID)
        hr = report["human_review"]
        assert hr["confirmed"] == 2 and hr["false_positive"] == 1
        assert hr["auto_confirmed"] == 1 and hr["manual_reviewed"] == 2
        # 剔除误报后 2 处：高 1 + 低 1
        assert hr["final_total"] == 2
        assert (hr["final_high"], hr["final_medium"], hr["final_low"]) == (1, 0, 1)
        # 下标对齐：逐条人工结论已附上
        assert report["violations"][1]["human_status"] == "false_positive"
        assert report["violations"][2]["human_confirmed_by"] == 0
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == _TASK_ID).delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_refresh_report_rewrites_on_new_decisions(tmp_path):
    db = SessionLocal()
    try:
        _seed_results(db)
        base = {
            "task_id": _TASK_ID, "document_name": "d", "generated_at": "2026-01-01T00:00:00",
            "summary": {"total_violations": 3, "high_risk": 1, "medium_risk": 1, "low_risk": 1},
            "violations": [{"original_text": "a"}, {"original_text": "b"},
                           {"original_text": "c"}],
        }
        json_path = tmp_path / "task_x.json"
        json_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
        task = SimpleNamespace(id=_TASK_ID, report_path=str(json_path))

        first = refresh_report(db, task)
        assert "human_review" in first
        assert "人工复核" in json_path.with_suffix(".md").read_text(encoding="utf-8")

        # 无新判定 → 命中缓存不再重写
        before = json_path.read_text(encoding="utf-8")
        assert refresh_report(db, task) == first

        # 新的人工判定落库 → 过期重算，final 计数变化
        row = db.query(ReviewResult).filter(ReviewResult.task_id == _TASK_ID).first()
        row.status = "false_positive"
        row.confirmed_at = datetime.now()
        row.confirmed_by = 9
        db.commit()
        second = refresh_report(db, task)
        assert second["human_review"]["false_positive"] == 2
        assert second["human_review"]["final_total"] == 1
        assert json_path.read_text(encoding="utf-8") != before
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == _TASK_ID).delete()
        db.commit()
        db.close()
