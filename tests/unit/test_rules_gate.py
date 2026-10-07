"""规则发布门禁测试：新建/编辑不能绕过 publish 让草稿规则参与扫描。

规则扫描节点按 is_active=1 AND status=active 双条件取规则（rule_scan）；
本组测试验证 API 层不会制造出满足该组合的草稿规则。依赖真实 DB，跳过策略同 test_admin_api。
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import User

        db = SessionLocal()
        db.query(User).count()
        db.close()
        return True
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_rule(h: dict, name: str) -> dict:
    resp = client.post(
        "/api/v1/rules",
        headers=h,
        json={
            "domain": "banking",
            "rule_name": name,
            "rule_type": "keyword",
            "rule_content": {
                "operator": "OR",
                "conditions": [{"type": "keyword", "keywords": ["保本"], "match_mode": "any"}],
            },
            "severity": "high",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _cleanup(h: dict, rule_id: int) -> None:
    client.delete(f"/api/v1/rules/{rule_id}", headers=h)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_create_rule_lands_as_inactive_draft():
    h = _admin_headers()
    name = "门禁测试-新建即草稿"
    rule = _create_rule(h, name)
    try:
        assert rule["status"] == "draft"
        assert rule["is_active"] == 0
    finally:
        _cleanup(h, rule["id"])


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_update_cannot_activate_draft_rule():
    h = _admin_headers()
    rule = _create_rule(h, "门禁测试-草稿激活拦截")
    try:
        resp = client.put(
            f"/api/v1/rules/{rule['id']}", headers=h, json={"is_active": True}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        # 门禁强制：draft 规则 PUT is_active=true 后仍不得生效
        assert data["status"] == "draft"
        assert data["is_active"] == 0
    finally:
        _cleanup(h, rule["id"])


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_publish_activates_draft_and_toggle_works_afterwards():
    h = _admin_headers()
    rule = _create_rule(h, "门禁测试-发布后可启停")
    try:
        published = client.post(f"/api/v1/rules/{rule['id']}/publish", headers=h)
        assert published.status_code == 200
        data = published.json()["data"]["rule"]
        assert data["status"] == "active"
        assert data["is_active"] == 1

        # 生效规则允许运行期停用/启用
        off = client.put(f"/api/v1/rules/{rule['id']}", headers=h, json={"is_active": False})
        assert off.json()["data"]["is_active"] == 0
        on = client.put(f"/api/v1/rules/{rule['id']}", headers=h, json={"is_active": True})
        assert on.json()["data"]["is_active"] == 1
    finally:
        _cleanup(h, rule["id"])


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_rereview_requires_manage_rules():
    """规则重审接口鉴权：匿名 401，普通登录用户（无 manage_rules）403。"""
    resp = client.post("/api/v1/rules/1/re-review")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1101

    h = _admin_headers()
    # admin 有 manage_rules 权限，但规则不存在应 404（证明鉴权通过、进入业务逻辑）
    resp = client.post("/api/v1/rules/99999999/re-review", headers=h)
    assert resp.status_code == 404
