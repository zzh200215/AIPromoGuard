"""Neo4j 客户端单元测试。

真实 Neo4j 仅在 `docker compose --profile graph` 下运行；测试在不可用时自动跳过
连通性用例，但优雅降级路径（driver 未初始化 → 返回空）始终可验证。
含快速失败冷却用例（PR-9：服务不可达后不再逐查询付重连代价）。
"""

import pytest
import src.infrastructure.database.neo4j_client as nc


@pytest.fixture(autouse=True)
def _reset_cooldown():
    """隔离冷却状态：避免测试间（及与真实运行）相互污染。"""
    nc._clear_cooldown()
    yield
    nc._clear_cooldown()


def test_run_cypher_graceful_when_driver_unavailable(monkeypatch):
    """Neo4j 不可用时 run_cypher 返回空列表，不抛异常（降级策略）。"""
    monkeypatch.setattr(nc, "get_driver", lambda: None)
    assert nc.run_cypher("RETURN 1") == []
    assert nc.health() is False


class _FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, *args, **kwargs):
        raise nc.ServiceUnavailable("connection refused")


class _OkResult:
    def consume(self):
        return None


class _OkSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, *args, **kwargs):
        return _OkResult()


def test_run_cypher_fast_fail_cooldown(monkeypatch):
    """服务不可达后进入冷却：冷却期内不再触碰 driver（快速降级），到期自动重探。"""
    calls = {"n": 0}

    class _FailingDriver:
        def session(self, **kwargs):
            calls["n"] += 1
            return _FailingSession()

    monkeypatch.setattr(nc, "get_driver", lambda: _FailingDriver())

    # 第一次：真实尝试 → ServiceUnavailable → 标记冷却
    assert nc.run_cypher("RETURN 1") == []
    assert calls["n"] == 1
    assert nc._in_cooldown()

    # 冷却期内：直接返回空，不再触碰 driver
    assert nc.run_cypher("RETURN 1") == []
    assert calls["n"] == 1

    # 冷却到期（模拟时间推进）→ 重新尝试一次
    monkeypatch.setattr(nc, "_unavailable_until", 0.0)
    assert nc.run_cypher("RETURN 1") == []
    assert calls["n"] == 2


def test_health_success_clears_cooldown(monkeypatch):
    """health() 探测成功时立即清除冷却（服务恢复后查询不必等冷却到期）。"""
    nc._mark_unavailable()
    assert nc._in_cooldown()

    class _OkDriver:
        def session(self, **kwargs):
            return _OkSession()

    monkeypatch.setattr(nc, "get_driver", lambda: _OkDriver())
    assert nc.health() is True
    assert not nc._in_cooldown()


@pytest.mark.skipif(
    not nc.health(), reason="Neo4j 未运行（docker compose --profile graph up -d neo4j）"
)
def test_roundtrip_with_live_neo4j():
    """真实 Neo4j 可用时：建节点 → 查询 → 删除 全链路。"""
    marker = "test_violation_pattern"
    nc.run_cypher(
        "MERGE (v:ViolationPattern {pattern_name: $name}) RETURN v",
        {"name": marker},
    )
    rows = nc.run_cypher(
        "MATCH (v:ViolationPattern {pattern_name: $name}) RETURN v.pattern_name AS name",
        {"name": marker},
    )
    assert rows and rows[0]["name"] == marker
    nc.run_cypher(
        "MATCH (v:ViolationPattern {pattern_name: $name}) DETACH DELETE v",
        {"name": marker},
    )
    assert nc.run_cypher(
        "MATCH (v:ViolationPattern {pattern_name: $name}) RETURN v",
        {"name": marker},
    ) == []
