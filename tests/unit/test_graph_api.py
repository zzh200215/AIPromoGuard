"""知识图谱接口测试（W9 周四）。Neo4j 不可用时跳过真实查询用例。"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.infrastructure.database import neo4j_client as nc

client = TestClient(app)


def _auth_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_graph_query_requires_auth():
    r = client.post("/api/v1/graph/query", json={"query": "承诺保本保收益"})
    assert r.status_code == 401


def test_graph_query_invalid_domain():
    r = client.post(
        "/api/v1/graph/query",
        headers=_auth_headers(),
        json={"query": "承诺保本保收益", "domain": "xyz"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == 1001  # 参数错误


@pytest.mark.skipif(
    not nc.health(), reason="Neo4j 未运行（docker compose --profile graph up -d neo4j）"
)
def test_graph_query_ok():
    r = client.post(
        "/api/v1/graph/query",
        headers=_auth_headers(),
        json={"query": "承诺保本保收益", "domain": "banking", "top_k": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total_matched"] >= 1
    assert any("保本保收益" in p["pattern_name"] for p in data["patterns"])
    assert data["regulations"]  # 关联到资管新规 / 理财办法
    assert data["cases"]  # 关联到历史处罚案例


@pytest.mark.skipif(not nc.health(), reason="Neo4j 未运行")
def test_graph_cases_recommend_ok():
    r = client.post(
        "/api/v1/graph/cases/recommend",
        headers=_auth_headers(),
        json={"text": "宣传预期收益率误导投资者", "domain": "fund", "top_k": 3},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 1
    assert "similarity" in data["cases"][0]
    assert data["cases"][0]["similarity"] > 0


@pytest.mark.skipif(not nc.health(), reason="Neo4j 未运行")
def test_graph_stats_ok():
    r = client.get("/api/v1/graph/stats", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["nodes"]["PenaltyCase"] >= 1
