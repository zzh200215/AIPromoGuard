"""stage_log 节点级增量落库（实时轨迹修复）单元测试。

覆盖四件事：
1. _wrap 成功路径回调 persist_stage（task_id / 节点名 / 含 status+cost 的条目）；
2. interrupt 与异常路径不回调（半途节点不该被点亮）；
3. persist_stage 的入参防线与单测环境防线（PYTEST 下不触碰任何真实连接）；
4. persist_stage 的合并语句形态（JSON_MERGE_PATCH + 参数绑定）与失败静默。
"""

import json

import pytest
import src.services.stage_sink as stage_sink_mod
from langgraph.errors import GraphInterrupt
from src.core.agents.graph import _wrap


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, task_id, name, entry):
        self.calls.append((task_id, name, entry))


def _fake_node(state):
    return {"domain": "fund"}


# ---------- _wrap 回调语义 ----------


def test_wrap_flushes_stage_on_success(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(stage_sink_mod, "persist_stage", rec)
    wrapped = _wrap(_fake_node, "classify")
    result = wrapped({"task_id": 42})
    assert result["stage_log"]["classify"]["status"] == "completed"
    assert len(rec.calls) == 1
    task_id, name, entry = rec.calls[0]
    assert task_id == 42 and name == "classify"
    assert entry["status"] == "completed" and "cost_ms" in entry


def test_wrap_no_flush_without_task_id(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(stage_sink_mod, "persist_stage", rec)
    wrapped = _wrap(_fake_node, "classify")
    wrapped({})
    assert rec.calls == []


def test_wrap_no_flush_on_interrupt(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(stage_sink_mod, "persist_stage", rec)

    def _interrupt_node(state):
        raise GraphInterrupt([{"item": 1}])

    wrapped = _wrap(_interrupt_node, "human_review")
    with pytest.raises(GraphInterrupt):
        wrapped({"task_id": 42})
    assert rec.calls == []


def test_wrap_no_flush_on_failure(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(stage_sink_mod, "persist_stage", rec)

    def _boom(state):
        raise ValueError("node exploded")

    wrapped = _wrap(_boom, "llm_scan")
    with pytest.raises(ValueError):
        wrapped({"task_id": 42})
    assert rec.calls == []


# ---------- persist_stage 防线与语句形态 ----------


def test_persist_stage_input_guards():
    # task_id/name/entry 非法输入全部早退，不触碰任何连接（无异常即通过）
    stage_sink_mod.persist_stage(None, "llm_scan", {"status": "completed"})
    stage_sink_mod.persist_stage(0, "llm_scan", {"status": "completed"})
    stage_sink_mod.persist_stage(1, "", {"status": "completed"})
    stage_sink_mod.persist_stage(1, "llm_scan", "not-a-dict")


def test_persist_stage_skips_in_pytest_env():
    # 单测防线：当前就在 pytest 环境里，真实引擎不应被触碰（无异常即通过）
    stage_sink_mod.persist_stage(987654321, "llm_scan", {"status": "completed"})


def test_persist_stage_emits_merge_statement(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    import src.infrastructure.database.mysql as mysql_mod

    executed = []

    class _Conn:
        def execute(self, stmt, params):
            executed.append((str(stmt), params))

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *exc):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    monkeypatch.setattr(mysql_mod, "engine", _Engine())
    stage_sink_mod.persist_stage(77, "llm_scan", {"status": "completed", "cost_ms": 5})
    assert len(executed) == 1
    stmt, params = executed[0]
    assert "JSON_MERGE_PATCH" in stmt and "review_tasks" in stmt
    assert params["task_id"] == 77
    assert json.loads(params["entry"]) == {"llm_scan": {"status": "completed", "cost_ms": 5}}


def test_persist_stage_swallows_engine_failure(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    import src.infrastructure.database.mysql as mysql_mod

    class _Boom:
        def begin(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(mysql_mod, "engine", _Boom())
    # 静默降级：不抛异常即通过
    stage_sink_mod.persist_stage(77, "llm_scan", {"status": "completed"})


def test_persist_stage_skips_oversized_entry(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    import src.infrastructure.database.mysql as mysql_mod

    touched = []

    class _Engine:
        def begin(self):
            touched.append(1)
            raise AssertionError("超限条目不应触碰数据库")

    monkeypatch.setattr(mysql_mod, "engine", _Engine())
    huge = {"status": "completed", "blob": "x" * (stage_sink_mod._MAX_ENTRY_CHARS + 1)}
    stage_sink_mod.persist_stage(77, "llm_scan", huge)
    assert touched == []
