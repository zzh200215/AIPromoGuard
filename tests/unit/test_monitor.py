"""W14/W16 测试：系统监控端点 + 审计用户名修复（BUG）。

监控端点需 monitor 权限（admin）；审计用户名验证依赖真实 DB。
"""

import time

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal

client = TestClient(app)


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        from src.models import User

        db.query(User).count()
        db.close()
        return True
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_monitor_requires_permission():
    """非管理员（viewer）无 monitor 权限。"""
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    # 造一个 viewer 用户测试越权（若已存在则复用）
    h = _admin_headers()
    created = client.post(
        "/api/v1/users", headers=h,
        json={"username": "mon_v", "password": "secret123", "role": "viewer"},
    )
    if created.status_code == 201:
        v_login = client.post(
            "/api/v1/auth/login",
            json={"username": "mon_v", "password": "secret123"},
        )
        v_h = {"Authorization": f"Bearer {v_login.json()['data']['access_token']}"}
        r = client.get("/api/v1/system/monitor", headers=v_h)
        assert r.status_code == 403
        # 清理
        uid = created.json()["data"]["id"]
        client.delete(f"/api/v1/users/{uid}", headers=h)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_monitor_ok():
    r = client.get("/api/v1/system/monitor", headers=_admin_headers())
    assert r.status_code == 200
    data = r.json()["data"]
    assert "tasks" in data and "database" in data and "vector_store" in data
    assert data["database"]["ok"] is True
    assert data["database"]["knowledge_base"]["regulations"] >= 1
    assert "graph" in data and "audit" in data


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_audit_logs_store_real_username():
    """BUG 修复：审计日志 username 应存真实用户名而非角色。"""
    h = _admin_headers()
    r = client.get("/api/v1/graph/stats", headers=h)  # 触发一次审计写入
    assert r.status_code == 200
    time.sleep(1.0)  # 审计后台线程异步落库

    db = SessionLocal()
    try:
        from src.models import AuditLog

        row = (
            db.query(AuditLog)
            .filter(AuditLog.action == "GET /api/v1/graph/stats")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.username == "admin"  # 真实用户名，而非角色
    finally:
        db.close()
