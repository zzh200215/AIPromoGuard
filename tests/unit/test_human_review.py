"""人工复核关卡（LangGraph interrupt + checkpointer）测试。

覆盖：
- 节点逻辑：未启用直通 / 无待复核项 / 决策过滤 merged_findings；
- 图级 interrupt-resume：真实 InMemorySaver checkpoint，暂停时图停在
  human_review，Command(resume=...) 后续跑 risk_assess → report，
  被否决结论不出现在报告；
- 服务层守卫：非 awaiting_review 状态拒绝提交决策。
"""

from types import SimpleNamespace

import pytest
import src.core.agents.nodes.human_review as hr
from langgraph.checkpoint.memory import InMemorySaver
from src.core.agents import runtime
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewTask, Rule
from src.services.review_service import resume_human_review
from src.utils.errors import AppError, ErrorCode


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.query(Rule).count()
        db.close()
        return True
    except Exception:
        return False


def _cfg(enabled: bool) -> SimpleNamespace:
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


# ---------- 节点逻辑 ----------

def test_human_review_disabled_passthrough(monkeypatch):
    monkeypatch.setattr(hr, "settings", _cfg(enabled=False))
    findings = [_finding(severity="high"), _finding(source="hybrid")]
    assert hr.human_review({"merged_findings": findings}) == {}


def test_human_review_enabled_no_pending(monkeypatch):
    monkeypatch.setattr(hr, "settings", _cfg(enabled=True))
    findings = [_finding(source="rule", severity="medium"), _finding(source="llm")]
    result = hr.human_review({"merged_findings": findings})
    assert result == {"human_review": {"required": False, "rejected_indexes": []}}


def test_human_review_pending_selection(monkeypatch):
    """severity=high 或 source=hybrid 进入待复核清单。"""
    monkeypatch.setattr(hr, "settings", _cfg(enabled=True))
    findings = [
        _finding(source="rule", severity="high"),      # severity 命中
        _finding(source="rule", severity="medium"),    # 不命中
        _finding(source="hybrid", severity="low"),     # source 命中
        _finding(source="llm", severity="medium"),     # 不命中
    ]
    assert hr._pending_indexes(findings, {"high"}, {"hybrid"}) == [0, 2]


# ---------- 图级 interrupt / resume ----------

SAMPLE = "本理财产品保本保收益，零风险，预期年化收益率5.8%，本金无忧，稳赚不赔。"


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_graph_interrupt_and_resume(monkeypatch, tmp_path):
    from src.core.agents.graph import build_graph

    monkeypatch.setattr(hr, "settings", _cfg(enabled=True))
    # 跳过 LLM（规则命中足以触发 high 待复核）；报告写到临时目录
    import src.core.agents.nodes.llm_scan as llm_scan_mod

    monkeypatch.setattr(llm_scan_mod, "get_llm", lambda: None)
    monkeypatch.setattr(
        "src.core.agents.nodes.report.settings",
        SimpleNamespace(report_dir=str(tmp_path)),
    )

    graph = build_graph(checkpointer=InMemorySaver())
    monkeypatch.setattr(runtime, "_HIL_GRAPH", graph)  # runtime 助手复用本图

    state = {
        "task_id": 9876551,
        "document_name": "hil测试.txt",
        "document_path": "/tmp/hil.txt",
        "doc_type": "txt",
        "text": SAMPLE,
        "blocks": [{"text": SAMPLE, "page": 1, "paragraph": 1, "heading": False}],
    }
    thread = "hil-test-thread"
    outcome = runtime.start_review_with_hil(state, thread)
    assert outcome["interrupted"] is True
    pending = outcome["pending"]
    assert isinstance(pending, list) and len(pending) >= 1
    assert all("index" in p and "description" in p for p in pending)

    snapshot = graph.get_state({"configurable": {"thread_id": thread}})
    total_before = len(snapshot.values.get("merged_findings", []))
    rejected = [pending[0]["index"]]

    result = runtime.resume_review(thread, {"rejected_indexes": rejected})
    report = result["report"]
    assert result["human_review"]["rejected_indexes"] == rejected
    # 被否决结论被剔除，其余 1:1 进入报告
    assert report["summary"]["total_violations"] == total_before - len(rejected)
    assert result["stage_log"]["human_review"]["status"] == "completed"
    assert (tmp_path / "task_9876551.json").exists()

    # checkpoint 已到终点（无待执行节点）；对同一 thread 重新传 input 属于
    # LangGraph 开启新一轮运行的语义，不是续跑
    final_state = graph.get_state({"configurable": {"thread_id": thread}})
    assert final_state.next == ()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_resume_rejects_wrong_task_state():
    """非 awaiting_review 状态提交决策 → TASK_INVALID_STATE。"""
    db = SessionLocal()
    task = ReviewTask(
        task_name="状态守卫测试",
        document_name="guard.txt",
        status="completed",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()
    try:
        with pytest.raises(AppError) as exc:
            resume_human_review(task_id, [])
        assert exc.value.code == ErrorCode.TASK_INVALID_STATE
    finally:
        db = SessionLocal()
        db.query(ReviewTask).filter(ReviewTask.id == task_id).delete()
        db.commit()
        db.close()
