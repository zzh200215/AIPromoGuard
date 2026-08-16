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
