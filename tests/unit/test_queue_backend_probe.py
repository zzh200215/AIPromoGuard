"""队列后端探测并发安全测试（PR-9）。

背景：`_use_celery()` 的首次探测（celery control.ping）在多线程并发调用下
有概率挂死（实测 20 线程并发把提交阶段卡住 100s+，任务全量 pending）——
修复为锁内双检：并发首探只真正 ping 一次，其余线程复用结果。
"""

import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor

import src.services.review_service as rs


def test_use_celery_probe_serialized_under_concurrency(monkeypatch):
    """8 线程并发首探：ping 只执行一次（锁 + 双检），结果一致。"""
    calls: list[int] = []

    def fake_ping(timeout=0.5):
        calls.append(1)
        time.sleep(0.1)  # 放大并发窗口：无锁时 8 个线程都会进探测
        return []

    class _FakeControl:
        @staticmethod
        def ping(timeout=0.5):
            return fake_ping(timeout)

    class _FakeApp:
        control = _FakeControl()

    fake_mod = types.ModuleType("src.infrastructure.queue.celery_app")
    fake_mod.celery_app = _FakeApp()
    monkeypatch.setitem(sys.modules, "src.infrastructure.queue.celery_app", fake_mod)

    # 重置探测缓存：确保全部线程都走"首探"路径
    monkeypatch.setattr(rs, "_QUEUE_BACKEND", None)
    monkeypatch.setattr(rs, "_LAST_CHECK", 0.0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: rs._use_celery(), range(8)))

    assert results == [False] * 8  # 无 worker → thread 后端
    assert len(calls) == 1  # 锁 + 双检：并发首探只 ping 一次


def test_use_celery_cache_hit_within_ttl(monkeypatch):
    """TTL 内命中缓存：不再 ping。"""
    calls: list[int] = []

    class _FakeControl:
        @staticmethod
        def ping(timeout=0.5):
            calls.append(1)
            return [{"celery@host": {"ok": "pong"}}]

    class _FakeApp:
        control = _FakeControl()

    fake_mod = types.ModuleType("src.infrastructure.queue.celery_app")
    fake_mod.celery_app = _FakeApp()
    monkeypatch.setitem(sys.modules, "src.infrastructure.queue.celery_app", fake_mod)

    monkeypatch.setattr(rs, "_QUEUE_BACKEND", None)
    monkeypatch.setattr(rs, "_LAST_CHECK", 0.0)

    assert rs._use_celery() is True  # 有 worker → celery 后端
    assert rs._use_celery() is True  # TTL 内命中缓存
    assert len(calls) == 1
