"""监管动态 API 测试：列表 / 手动录入 / 确认 / 忽略 / 越权 403。"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import Regulation, RegulationUpdate

client = TestClient(app)


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_list_updates_structure():
    h = _admin_headers()
    r = client.get("/api/v1/regulatory-updates", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert "total" in data and "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_manual_create_confirm_ignore_flow():
    h = _admin_headers()
    title = f"监管动态API测试法规{int(time.time())}"

    # 手动录入
    created = client.post(
        "/api/v1/regulatory-updates", headers=h,
        json={
            "source": "pbc",
            "title": title,
            "doc_no": "〔2026〕第1号",
            "publish_date": "2026-08-01",
        },
    )
    assert created.status_code == 200
    uid = created.json()["data"]["id"]
    assert created.json()["data"]["match_type"] == "manual"

    # 列表可见
    listed = client.get(
        "/api/v1/regulatory-updates", headers=h, params={"status": "pending"}
    ).json()["data"]
    assert any(it["id"] == uid for it in listed["items"])

    # 确认入库
    confirmed = client.post(f"/api/v1/regulatory-updates/{uid}/confirm", headers=h, json={})
    assert confirmed.status_code == 200
    rid = confirmed.json()["data"]["regulation_id"]
    assert confirmed.json()["data"]["regulation_name"] == title

    # 法规库出现新法规
    regs = client.get("/api/v1/regulations", headers=h, params={"keyword": title}).json()["data"]
    assert any(r["id"] == rid for r in regs["items"])

    # 已入库状态再确认 → 409
    again = client.post(f"/api/v1/regulatory-updates/{uid}/confirm", headers=h, json={})
    assert again.status_code == 409

    # 清理
    db = SessionLocal()
    db.query(RegulationUpdate).filter(RegulationUpdate.id == uid).delete()
    db.query(Regulation).filter(Regulation.id == rid).delete()
    db.commit()
    db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_ignore_updates():
    h = _admin_headers()
    title = f"监管动态API忽略{int(time.time())}"
    created = client.post(
        "/api/v1/regulatory-updates", headers=h, json={"source": "nfra", "title": title}
    ).json()["data"]
    uid = created["id"]

    ignored = client.post(f"/api/v1/regulatory-updates/{uid}/ignore", headers=h)
    assert ignored.status_code == 200

    db = SessionLocal()
    db.query(RegulationUpdate).filter(RegulationUpdate.id == uid).delete()
    db.commit()
    db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_confirm_requires_manage_regulations_permission():
    h = _admin_headers()
    # 建一条 pending 记录
    title = f"监管动态权限测试{int(time.time())}"
    created = client.post(
        "/api/v1/regulatory-updates", headers=h, json={"source": "pbc", "title": title}
    ).json()["data"]
    uid = created["id"]

    # 创建 reviewer 用户（无 manage_regulations 权限）并登录
    username = f"trend_rev_{int(time.time())}"
    client.post(
        "/api/v1/users", headers=h,
        json={"username": username, "password": "secret123", "role": "reviewer"},
    )
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    reviewer_headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    r = client.post(f"/api/v1/regulatory-updates/{uid}/confirm", headers=reviewer_headers, json={})
    assert r.status_code == 403

    # 清理
    listed = client.get("/api/v1/users", headers=h).json()["data"]["items"]
    for u in listed:
        if u["username"] == username:
            client.delete(f"/api/v1/users/{u['id']}", headers=h)
    db = SessionLocal()
    db.query(RegulationUpdate).filter(RegulationUpdate.id == uid).delete()
    db.commit()
    db.close()
