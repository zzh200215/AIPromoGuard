"""管理后台接口测试（W12）：用户管理 + 法规条款管理。

依赖真实 DB（admin 账号），DB 不可用时跳过。
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

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


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_admin_user_crud_flow():
    h = _admin_headers()
    username = "w12_test_user"

    # 清理历史残留（幂等）
    listed = client.get("/api/v1/users", headers=h).json()["data"]["items"]
    for u in listed:
        if u["username"] == username:
            client.delete(f"/api/v1/users/{u['id']}", headers=h)

    # 创建
    created = client.post(
        "/api/v1/users", headers=h,
        json={
            "username": username,
            "password": "secret123",
            "role": "reviewer",
            "department": "合规部",
        },
    )
    assert created.status_code == 201
    uid = created.json()["data"]["id"]
    assert created.json()["data"]["role"] == "reviewer"

    # 重复创建 → 409
    dup = client.post(
        "/api/v1/users", headers=h,
        json={"username": username, "password": "secret123", "role": "reviewer"},
    )
    assert dup.status_code == 409

    # 重置密码（用户仍启用）→ 新密码可登录
    client.post(f"/api/v1/users/{uid}/password", headers=h, json={"password": "newpass456"})
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "newpass456"})
    assert login.status_code == 200

    # 更新角色 + 禁用 → 被禁用用户无法登录
    updated = client.put(
        f"/api/v1/users/{uid}", headers=h, json={"role": "viewer", "status": 0}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["role"] == "viewer"
    assert updated.json()["data"]["status"] == 0

    blocked = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "newpass456"},
    )
    assert blocked.status_code == 403

    # 删除
    deleted = client.delete(f"/api/v1/users/{uid}", headers=h)
    assert deleted.status_code == 200


def test_admin_cannot_manage_self():
    """管理员不能修改/删除自己，防止锁死管理入口。"""
    h = _admin_headers()
    me = client.get("/api/v1/auth/me", headers=h).json()["data"]
    uid = me["id"]
    r = client.delete(f"/api/v1/users/{uid}", headers=h)
    assert r.status_code == 400
    r2 = client.put(f"/api/v1/users/{uid}", headers=h, json={"status": 0})
    assert r2.status_code == 400


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_regulation_articles_crud():
    h = _admin_headers()
    # 取一部法规
    regs = client.get("/api/v1/regulations", headers=h).json()["data"]["items"]
    assert regs
    rid = regs[0]["id"]

    # 新增条款
    created = client.post(
        f"/api/v1/regulations/{rid}/articles", headers=h,
        json={"article_no": "测试条", "content": "测试条款内容，不得承诺保本保收益。"},
    )
    assert created.status_code == 201
    aid = created.json()["data"]["id"]

    # 列表可见
    listed = client.get(f"/api/v1/regulations/{rid}/articles", headers=h).json()["data"]
    assert any(a["id"] == aid for a in listed["items"])

    # 更新（触发向量失效）
    updated = client.put(
        f"/api/v1/regulations/articles/{aid}", headers=h, json={"content": "更新后的测试条款内容。"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["vector_id"] is None

    # 删除
    deleted = client.delete(f"/api/v1/regulations/articles/{aid}", headers=h)
    assert deleted.status_code == 200
