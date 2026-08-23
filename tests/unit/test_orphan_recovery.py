"""孤儿任务自愈测试：进程崩溃遗留的 running 任务在启动时被回收。

- 无 checkpoint 的 running 任务 → 置 failed（批次计数同步）；
- checkpoint 停在 human_review 中断 → 恢复 awaiting_review，待复核清单从
  中断 payload 重建，人工决策仍可从持久化 checkpoint 续跑到终点；
- Celery worker 在线时跳过（执行权在 worker 进程，API 不误杀在跑任务）。
"""

from types import SimpleNamespace

import pytest
import src.core.agents.nodes.human_review as hr
import src.core.agents.nodes.llm_scan as llm_scan_mod
import src.core.agents.nodes.report as report_mod
import src.core.agents.runtime as runtime
import src.services.review_service as rs
from sqlalchemy import text
from src.core.agents.graph import build_graph
from src.infrastructure.database.langgraph_saver import MySQLCheckpointSaver
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewTask
from src.services.review_service import recover_orphan_tasks, resume_human_review

SAMPLE = "本理财产品保本保收益，零风险，预期年化收益率5.8%，本金无忧，稳赚不赔。"


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _hil_on(monkeypatch, tmp_path):
    """打开人工复核并关闭 LLM/报告落盘，保证图运行确定性。"""
    monkeypatch.setattr(
        hr,
        "settings",
        SimpleNamespace(
            app_config=lambda section: (
                {
                    "human_review": {
                        "enabled": True,
                        "review_severities": ["high"],
                        "review_sources": ["hybrid"],
                    }
                }
                if section == "workflow"
                else {}
            )
        ),
    )
    monkeypatch.setattr(llm_scan_mod, "get_llm", lambda: None)
    monkeypatch.setattr(report_mod, "settings", SimpleNamespace(report_dir=str(tmp_path)))
    monkeypatch.setattr(rs, "_human_review_enabled", lambda: True)
    monkeypatch.setattr(rs, "_use_celery", lambda: False)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_recover_running_without_checkpoint(monkeypatch):
    monkeypatch.setattr(rs, "_human_review_enabled", lambda: True)
    monkeypatch.setattr(rs, "_use_celery", lambda: False)
    db = SessionLocal()
    try:
        task = ReviewTask(task_name="无检查点孤儿", document_name="x.txt", status="running")
        db.add(task)
        db.commit()
        tid = task.id
        db.expire_all()

        outcome = recover_orphan_tasks()
        assert outcome["failed"] >= 1 and outcome["recovered"] == 0

        db.rollback()
        db.expire_all()
        after = db.get(ReviewTask, tid)
        assert after.status == "failed" and after.progress == 100
    finally:
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_recover_interrupted_to_awaiting_review(monkeypatch, tmp_path):
    _hil_on(monkeypatch, tmp_path)
    db = SessionLocal()
    try:
        task = ReviewTask(task_name="中断恢复孤儿", document_name="x.txt", status="running")
        db.add(task)
        db.commit()
        tid = task.id
        db.close()

        # 模拟崩溃现场：图跑到 human_review 中断，但任务状态没来得及写 awaiting_review
        graph = build_graph(checkpointer=MySQLCheckpointSaver())
        monkeypatch.setattr(runtime, "_HIL_GRAPH", graph)
        state = {
            "task_id": tid,
            "document_name": "孤儿.txt",
            "document_path": "/tmp/x.txt",
            "doc_type": "txt",
            "text": SAMPLE,
            "blocks": [{"text": SAMPLE, "page": 1, "paragraph": 1, "heading": False}],
        }
        outcome = runtime.start_review_with_hil(state, runtime.thread_id_for_task(tid))
        assert outcome["interrupted"] is True

        outcome = recover_orphan_tasks()
        assert outcome["recovered"] >= 1

        db = SessionLocal()
        db.expire_all()
        after = db.get(ReviewTask, tid)
        assert after.status == "awaiting_review"
        pending = after.stages["human_review"]["pending"]
        assert len(pending) >= 1 and all("index" in p for p in pending)

        # 崩溃恢复后的完整故事：人工决策仍可从 checkpoint 续跑到终点
        summary = resume_human_review(tid, [pending[0]["index"]])
        assert summary["status"] == "completed"
        assert summary["human_review"]["rejected_indexes"] == [pending[0]["index"]]
    finally:
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_recover_skipped_when_celery_online(monkeypatch):
    monkeypatch.setattr(rs, "_use_celery", lambda: True)
    assert recover_orphan_tasks() == {"skipped": "celery"}
