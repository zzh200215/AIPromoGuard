"""审查任务队列测试（B2：Celery/Redis 队列 + 线程池回退）。

不依赖 DB / 真实 broker：monkeypatch 掉 worker 探测与任务发送。
"""

from types import SimpleNamespace

import src.services.review_service as rs


def _reset_backend_cache(monkeypatch):
    monkeypatch.setattr(rs, "_QUEUE_BACKEND", None)
    monkeypatch.setattr(rs, "_LAST_CHECK", 0.0)


def test_use_celery_fallback_no_workers(monkeypatch):
    """broker 有响应但无 worker（ping 返回空）→ 回退线程池。"""
    fake = SimpleNamespace(control=SimpleNamespace(ping=lambda **k: {}))
    monkeypatch.setattr("src.infrastructure.queue.celery_app.celery_app", fake)
    _reset_backend_cache(monkeypatch)
    assert rs._use_celery() is False
    assert rs._QUEUE_BACKEND == "thread"


def test_use_celery_broker_down(monkeypatch):
    """broker 不可达（ping 抛异常）→ 回退线程池。"""
    fake = SimpleNamespace(
        control=SimpleNamespace(ping=lambda **k: (_ for _ in ()).throw(ConnectionError))
    )
    monkeypatch.setattr("src.infrastructure.queue.celery_app.celery_app", fake)
    _reset_backend_cache(monkeypatch)
    assert rs._use_celery() is False


def test_use_celery_with_workers(monkeypatch):
    """有 worker 存活（ping 返回节点）→ 走 Celery 队列。"""
    fake = SimpleNamespace(
        control=SimpleNamespace(ping=lambda **k: {"worker1@host": {"ok": "pong"}})
    )
    monkeypatch.setattr("src.infrastructure.queue.celery_app.celery_app", fake)
    _reset_backend_cache(monkeypatch)
    assert rs._use_celery() is True
    assert rs._QUEUE_BACKEND == "celery"


def test_start_review_falls_back_to_thread(monkeypatch):
    """无 worker 时提交到线程池执行。"""
    calls = []
    monkeypatch.setattr(rs, "_use_celery", lambda: False)
    monkeypatch.setattr(
        rs, "_executor", SimpleNamespace(submit=lambda fn, tid: calls.append((fn, tid)))
    )
    rs.start_review(42)
    assert calls and calls[0][1] == 42


def test_start_review_sends_celery_task(monkeypatch):
    """有 worker 时入队 review.run_review。"""
    sent = []
    fake = SimpleNamespace(send_task=lambda name, args, queue: sent.append((name, args, queue)))
    monkeypatch.setattr("src.infrastructure.queue.celery_app.celery_app", fake)
    monkeypatch.setattr(rs, "_use_celery", lambda: True)
    rs.start_review(7)
    assert sent == [("review.run_review", [7], "review_tasks")]


# ---- 重复投递护栏（2026-10-24 Docker 崩溃重投事故）----

def test_execute_review_skips_completed_task(monkeypatch):
    """completed 是终态：重复投递/重复入队不重跑（防结果覆盖与配额双耗）。"""
    calls = {}
    task = SimpleNamespace(id=1, status="completed")
    monkeypatch.setattr(rs, "SessionLocal", lambda: SimpleNamespace(
        get=lambda m, tid: task,
        close=lambda: None,
    ))
    monkeypatch.setattr(rs.logger, "info", lambda *a, **k: calls.setdefault("skipped", True))
    monkeypatch.setattr(rs.document_service, "parse",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应触发解析")))
    rs.execute_review(1)
    assert calls.get("skipped") is True


def test_execute_review_runs_non_terminal(monkeypatch):
    """非终态（pending/failed 复位/running 续跑）正常进入执行路径。"""
    task = SimpleNamespace(id=2, status="pending", document_path="x.txt",
                           base_document_path=None, batch_id=None)
    db = SimpleNamespace(get=lambda m, tid: task, commit=lambda: None,
                         rollback=lambda: None, close=lambda: None)
    monkeypatch.setattr(rs, "SessionLocal", lambda: db)
    monkeypatch.setattr(rs.document_service, "parse",
                        lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("probe")))
    # execute_review 吞异常转 failed（通知/清理自护栏）；probe 效果 = 状态机走完
    # pending → running → failed，证明未被 completed 护栏拦截
    rs.execute_review(2)
    assert task.status == "failed"
