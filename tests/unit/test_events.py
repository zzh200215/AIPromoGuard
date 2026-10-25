"""SSE 事件总线与端点测试（P1-1，机制级零 Redis 依赖）。"""

import json
from types import SimpleNamespace

import src.services.event_bus as eb
from src.api.routers.events import _resolve_user


def test_publish_event_payload_shape(monkeypatch):
    """发布 payload 含 type/task/batch/user/data/ts 五要素，通道固定。"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # 解除环境护栏
    captured = {}
    fake = SimpleNamespace(
        publish=lambda ch, body: captured.update(channel=ch, body=body),
    )
    monkeypatch.setattr(eb, "_get_client", lambda: fake)
    eb.publish_event("task_status", {"status": "completed"}, task_id=7)
    assert captured["channel"] == eb.CHANNEL
    payload = json.loads(captured["body"])
    assert payload["type"] == "task_status"
    assert payload["task_id"] == 7
    assert payload["batch_id"] is None
    assert payload["user_id"] is None
    assert payload["data"] == {"status": "completed"}
    assert isinstance(payload["ts"], int)


def test_publish_event_user_scoped(monkeypatch):
    """通知类事件携带 user_id（SSE 连接层据此过滤跨用户）。"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    captured = {}
    monkeypatch.setattr(eb, "_get_client", lambda: SimpleNamespace(
        publish=lambda ch, body: captured.update(body=body),
    ))
    eb.publish_event("notification", {"title": "t"}, user_id=3)
    assert json.loads(captured["body"])["user_id"] == 3


def test_publish_event_silent_on_redis_failure(monkeypatch):
    """Redis 不可达：发布静默不外抛（增强能力不阻断主流程）。"""
    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(eb, "_get_client", _boom)
    eb.publish_event("task_status", {"status": "running"}, task_id=1)  # 不应抛


def test_publish_event_oversize_skipped(monkeypatch):
    """payload 超护栏：跳过发布（比写坏/撑爆订阅方安全）。"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    calls = []
    monkeypatch.setattr(eb, "_get_client", lambda: SimpleNamespace(
        publish=lambda ch, body: calls.append(body),
    ))
    eb.publish_event("task_stage", {"detail": "x" * 20_000}, task_id=1)
    assert calls == []


def test_resolve_user_token_query_or_header(monkeypatch):
    """SSE 认证：?token= 查询参数与 Bearer 头双通道；无效 token → None。"""
    request = SimpleNamespace(headers={"Authorization": "Bearer bad-token"})
    monkeypatch.setattr(
        "src.api.routers.events.decode_token",
        lambda t: (_ for _ in ()).throw(ValueError("bad")),
    )
    assert _resolve_user(request, None) is None

    monkeypatch.setattr(
        "src.api.routers.events.decode_token",
        lambda t: {"sub": "5", "role": "admin"},
    )
    db_user = SimpleNamespace(id=5)
    session = SimpleNamespace(get=lambda m, uid: db_user, close=lambda: None)
    monkeypatch.setattr("src.api.routers.events.SessionLocal", lambda: session)
    got = _resolve_user(SimpleNamespace(headers={}), "good-token")
    assert got is not None and got.id == 5
