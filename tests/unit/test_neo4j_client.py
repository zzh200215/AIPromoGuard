"""Neo4j 客户端单元测试。

真实 Neo4j 仅在 `docker compose --profile graph` 下运行；测试在不可用时自动跳过
连通性用例，但优雅降级路径（driver 未初始化 → 返回空）始终可验证。
"""

import pytest
import src.infrastructure.database.neo4j_client as nc


def test_run_cypher_graceful_when_driver_unavailable(monkeypatch):
    """Neo4j 不可用时 run_cypher 返回空列表，不抛异常（降级策略）。"""
    monkeypatch.setattr(nc, "get_driver", lambda: None)
    assert nc.run_cypher("RETURN 1") == []
    assert nc.health() is False


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
