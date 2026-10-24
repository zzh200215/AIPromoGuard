"""Copilot 多轮会话（第 2 批）：历史落库、上下文携带、恢复与失败卫生。

用打桩 LLM 捕获实际发送的 messages：第二轮必须携带第一轮的问答对
（多轮指代解析的机制保证），成功轮双双落库、失败轮不落。
"""

import json
from types import SimpleNamespace

import pytest
from src.services import review_copilot as rc

pytestmark = pytest.mark.usefixtures("_isolated_precedent_vectors")


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import ReviewTask

        db = SessionLocal()
        db.query(ReviewTask.id).limit(1).all()
        db.close()
        return True
    except Exception:
        return False


class _RecorderLLM:
    """记录每次调用收到的 messages，按序返回预置回答。"""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[list[dict]] = []

    def complete(self, messages, temperature=None):
        self.calls.append(messages)
        content = self.answers.pop(0)
        return SimpleNamespace(content=content, usage=None)


def _make_task(db, tmp_path):
    """建任务 + 最小报告文件（ask 上下文经 refresh_report 读取 report_path）。"""
    import json as _json

    from src.models import ReviewTask

    task = ReviewTask(
        task_name="多轮问答测试.txt",
        document_name="多轮问答测试.txt",
        domain="banking",
        status="completed",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    report_path = tmp_path / f"report-{task.id}.json"
    report_path.write_text(
        _json.dumps({"violations": [], "regulations": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    task.report_path = str(report_path)
    db.commit()
    return task


@pytest.fixture()
def db_session():
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    yield db
    db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_multiturn_history_carried_and_persisted(db_session, tmp_path, monkeypatch):
    task = _make_task(db_session, tmp_path)
    llm = _RecorderLLM(
        [
            json.dumps({"answer": "共 3 条违规，第 3 条是风险提示缺失", "refs": []}),
            json.dumps({"answer": "第 3 条指的是上一条回答里的披露缺失", "refs": []}),
        ]
    )
    monkeypatch.setattr(rc, "get_llm", lambda: llm)

    rc.ask_review_question(db_session, task, "本材料有几条违规？")
    rc.ask_review_question(db_session, task, "第 3 条具体指什么？")

    # 第二轮的 messages 携带第一轮问答对（多轮指代解析的机制保证）
    second = llm.calls[1]
    roles = [m["role"] for m in second]
    assert roles == ["system", "user", "assistant", "user"]
    assert "共 3 条违规" in second[2]["content"]

    # 历史双双落库：两轮 = user/assistant 共 4 条
    from src.models import CopilotMessage

    rows = (
        db_session.query(CopilotMessage)
        .filter_by(task_id=task.id)
        .order_by(CopilotMessage.id)
        .all()
    )
    assert [r.role for r in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[0].content == "本材料有几条违规？"
    assert "第 3 条" in rows[3].content


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_history_restored_in_order(db_session, tmp_path, monkeypatch):
    task = _make_task(db_session, tmp_path)
    llm = _RecorderLLM([json.dumps({"answer": "ok", "refs": []})])
    monkeypatch.setattr(rc, "get_llm", lambda: llm)
    rc.ask_review_question(db_session, task, "问题一")

    history = rc.load_copilot_history(db_session, task.id)
    assert len(history) == 2
    assert history[0]["role"] == "user" and history[0]["content"] == "问题一"
    assert history[1]["role"] == "assistant"


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_failed_call_persists_nothing(db_session, tmp_path, monkeypatch):
    """LLM 调用失败（抛 AppError）不落历史——保持成对干净数据。"""
    from src.models import CopilotMessage
    from src.utils.errors import AppError, ErrorCode

    task = _make_task(db_session, tmp_path)

    class _Boom:
        def complete(self, messages, temperature=None):
            raise RuntimeError("llm down")

    monkeypatch.setattr(rc, "get_llm", lambda: _Boom())
    with pytest.raises(AppError) as ei:
        rc.ask_review_question(db_session, task, "会失败的问题")
    assert ei.value.code == ErrorCode.LLM_CALL_FAILED
    assert db_session.query(CopilotMessage).filter_by(task_id=task.id).count() == 0
