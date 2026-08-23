"""MySQLCheckpointSaver（LangGraph checkpoint 持久化）测试。

覆盖：
- saver 原语：put/get_tuple 往返、parent 链、put_writes（含重写覆盖与异常对象
  序列化）、list（新→旧 / limit / before / 标量 filter）、get_next_version、
  delete_thread 清理；
- 关键生产场景：图在 human_review 中断后，用全新 saver 实例 + 全新编译图
  （模拟 API/worker 重启）从 MySQL checkpoint 续跑到终点——InMemorySaver 时代
  重启即丢 awaiting_review 任务的根因修复。
"""

import time
import uuid
from types import SimpleNamespace

import pytest
import src.core.agents.nodes.human_review as hr
import src.core.agents.nodes.llm_scan as llm_scan_mod
import src.core.agents.nodes.report as report_mod
from sqlalchemy import text
from src.core.agents import runtime
from src.core.agents.graph import build_graph
from src.infrastructure.database.langgraph_saver import MySQLCheckpointSaver
from src.infrastructure.database.mysql import engine

SAMPLE = "本理财产品保本保收益，零风险，预期年化收益率5.8%，本金无忧，稳赚不赔。"


def _db_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="数据库不可用")


def _fresh_thread() -> str:
    return f"cp-test-{uuid.uuid4().hex[:8]}"


def _checkpoint(cid: str, values: dict | None = None) -> dict:
    return {
        "v": 4,
        "id": cid,
        "ts": "2026-08-23T10:00:00+00:00",
        "channel_values": values if values is not None else {"text": "保本保收益", "count": 3},
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": [],
    }


def test_setup_idempotent():
    saver = MySQLCheckpointSaver()
    saver.setup()
    saver.setup()  # 已有库重复建表不报错


def test_put_get_roundtrip_and_parent_chain():
    saver = MySQLCheckpointSaver()
    saver.setup()
    thread = _fresh_thread()
    try:
        cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
        ret = saver.put(cfg, _checkpoint("cp-0001"), {"source": "loop", "step": 1}, {})
        assert ret["configurable"]["checkpoint_id"] == "cp-0001"

        cfg_with_parent = {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": "",
                "checkpoint_id": "cp-0001",
            }
        }
        saver.put(cfg_with_parent, _checkpoint("cp-0002"), {"source": "loop", "step": 2}, {})

        latest = saver.get_tuple({"configurable": {"thread_id": thread}})
        assert latest is not None
        assert latest.checkpoint["id"] == "cp-0002"
        assert latest.checkpoint["channel_values"]["count"] == 3  # 中文值不丢
        assert latest.metadata == {"source": "loop", "step": 2}
        assert latest.parent_config["configurable"]["checkpoint_id"] == "cp-0001"

        first = saver.get_tuple(
            {"configurable": {"thread_id": thread, "checkpoint_id": "cp-0001"}}
        )
        assert first.checkpoint["id"] == "cp-0001"
        assert first.parent_config is None

        assert saver.get_tuple({"configurable": {"thread_id": "no-such-thread"}}) is None
    finally:
        saver.delete_thread(thread)


def test_put_writes_pending_and_rewrite():
    saver = MySQLCheckpointSaver()
    saver.setup()
    thread = _fresh_thread()
    try:
        saver.put({"configurable": {"thread_id": thread}}, _checkpoint("cp-0001"), {}, {})
        cfg = {
            "configurable": {"thread_id": thread, "checkpoint_ns": "", "checkpoint_id": "cp-0001"}
        }
        saver.put_writes(
            cfg, [("findings", [1, 2, 3]), ("__error__", ValueError("boom"))], "task-a"
        )
        got = saver.get_tuple({"configurable": {"thread_id": thread, "checkpoint_id": "cp-0001"}})
        writes = {(w[0], w[1]): w[2] for w in got.pending_writes}
        assert writes[("task-a", "findings")] == [1, 2, 3]
        assert "boom" in str(writes[("task-a", "__error__")])  # 异常对象可序列化往返

        # 同 task 重写同 idx：REPLACE 覆盖而不是追加
        saver.put_writes(cfg, [("findings", [9])], "task-a")
        got = saver.get_tuple({"configurable": {"thread_id": thread, "checkpoint_id": "cp-0001"}})
        finding_writes = [w for w in got.pending_writes if w[1] == "findings"]
        assert finding_writes == [("task-a", "findings", [9])]

        with pytest.raises(ValueError):
            saver.put_writes(
                {"configurable": {"thread_id": thread}}, [("x", 1)], "task-b"
            )  # 缺 checkpoint_id
    finally:
        saver.delete_thread(thread)


def test_list_order_limit_before_filter():
    saver = MySQLCheckpointSaver()
    saver.setup()
    thread = _fresh_thread()
    try:
        base = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
        saver.put(base, _checkpoint("cp-0001"), {"step": 1}, {})
        saver.put(
            {**base, "configurable": {**base["configurable"], "checkpoint_id": "cp-0001"}},
            _checkpoint("cp-0002"),
            {"step": 2},
            {},
        )
        saver.put(
            {**base, "configurable": {**base["configurable"], "checkpoint_id": "cp-0002"}},
            _checkpoint("cp-0003"),
            {"step": 3},
            {},
        )

        ids = [t.checkpoint["id"] for t in saver.list({"configurable": {"thread_id": thread}})]
        assert ids == ["cp-0003", "cp-0002", "cp-0001"]  # 新→旧

        limited = list(saver.list({"configurable": {"thread_id": thread}}, limit=2))
        assert [t.checkpoint["id"] for t in limited] == ["cp-0003", "cp-0002"]

        before = saver.list(
            {"configurable": {"thread_id": thread}},
            before={"configurable": {"checkpoint_id": "cp-0003"}},
        )
        assert [t.checkpoint["id"] for t in before] == ["cp-0002", "cp-0001"]

        flt = saver.list({"configurable": {"thread_id": thread}}, filter={"step": 2})
        assert [t.checkpoint["id"] for t in flt] == ["cp-0002"]
        with pytest.raises(ValueError):
            list(saver.list(None, filter={"writes": {"a": 1}}))  # 仅支持标量
    finally:
        saver.delete_thread(thread)


def test_version_and_cleanup():
    saver = MySQLCheckpointSaver()
    saver.setup()
    assert saver.get_next_version(None, "ch") == 1
    assert saver.get_next_version(4, "ch") == 5

    thread = _fresh_thread()
    base = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    saver.put(base, _checkpoint("cp-0001"), {}, {})
    saver.put_writes(
        {**base, "configurable": {**base["configurable"], "checkpoint_id": "cp-0001"}},
        [("x", 1)],
        "task-a",
    )
    assert saver.delete_thread(thread) == 1
    assert saver.get_tuple({"configurable": {"thread_id": thread}}) is None
    with engine.begin() as conn:  # writes 也一并清理
        n = conn.execute(
            text("SELECT COUNT(*) FROM langgraph_writes WHERE thread_id = :t"), {"t": thread}
        ).scalar()
        assert n == 0


def test_interrupt_recovery_across_restart(monkeypatch, tmp_path):
    """重启恢复：进程 A 中断 → 全新 saver/图（进程 B）从 DB checkpoint 续跑。"""
    thread = f"restart-test-{int(time.time())}"
    saver = MySQLCheckpointSaver()
    saver.setup()
    try:
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

        # 进程 A：跑到 human_review 中断
        graph_a = build_graph(checkpointer=saver)
        monkeypatch.setattr(runtime, "_HIL_GRAPH", graph_a)
        state = {
            "task_id": 9876553,
            "document_name": "重启恢复.txt",
            "document_path": "/tmp/restart.txt",
            "doc_type": "txt",
            "text": SAMPLE,
            "blocks": [{"text": SAMPLE, "page": 1, "paragraph": 1, "heading": False}],
        }
        outcome = runtime.start_review_with_hil(state, thread)
        assert outcome["interrupted"] is True
        pending = outcome["pending"]
        assert len(pending) >= 1
        total_before = len(
            graph_a.get_state({"configurable": {"thread_id": thread}})
            .values.get("merged_findings", [])
        )

        # 进程 B：全新 saver 实例 + 全新编译图，仅凭 thread_id 找回中断点
        graph_b = build_graph(checkpointer=MySQLCheckpointSaver())
        monkeypatch.setattr(runtime, "_HIL_GRAPH", graph_b)
        snap = graph_b.get_state({"configurable": {"thread_id": thread}})
        assert snap.next == ("human_review",), "重启后应能看到中断点"

        rejected = [pending[0]["index"]]
        result = runtime.resume_review(thread, {"rejected_indexes": rejected})
        assert result["human_review"]["rejected_indexes"] == rejected
        assert result["report"]["summary"]["total_violations"] == total_before - len(rejected)
        assert graph_b.get_state({"configurable": {"thread_id": thread}}).next == ()
    finally:
        saver.delete_thread(thread)
