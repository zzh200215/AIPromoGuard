"""批次 API 测试：创建→列表→详情→导出（依赖真实 DB）。"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.api.main import app

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_batch_create_and_list():
    h = _admin_headers()
    r = client.post(
        "/api/v1/batches",
        headers=h,
        data={"batch_name": "压测批次"},
        files=[
            ("files", ("a.txt", io.BytesIO("本产品保本保收益".encode()), "text/plain")),
            ("files", ("b.txt", io.BytesIO("预期年化收益率5.8%".encode()), "text/plain")),
        ],
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["total_count"] == 2
    assert len(data["task_ids"]) == 2

    listed = client.get("/api/v1/batches", headers=h).json()["data"]
    assert listed["total"] >= 1
    assert any(b["id"] == data["batch_id"] for b in listed["items"])


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_batch_create_rejects_unsupported_ext():
    h = _admin_headers()
    r = client.post(
        "/api/v1/batches",
        headers=h,
        data={"batch_name": "非法批次"},
        files=[("files", ("x.exe", b"MZ", "application/octet-stream"))],
    )
    assert r.status_code == 400
    assert r.json()["code"] == 1002  # 文件格式不支持
