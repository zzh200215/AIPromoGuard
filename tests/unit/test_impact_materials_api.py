"""产品材料台账 API 测试：列表筛选 / 新增（document_id 白名单）/ 更新与归档。"""

import pytest
from fastapi.testclient import TestClient
from scripts.demo.seed_impact_demo import reset_demo, seed_demo
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import ProductMaterial

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
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_material_crud_flow():
    db = SessionLocal()
    try:
        seed_demo(db)
        h = _admin_headers()

        listed = client.get("/api/v1/impact/materials", headers=h,
                            params={"product_type": "fund"}).json()["data"]
        assert listed["total"] >= 10

        created = client.post(
            "/api/v1/impact/materials",
            headers=h,
            json={
                "name": "台账测试材料",
                "product_type": "insurance",
                "material_type": "海报",
                "owner": "测试员",
            },
        )
        assert created.status_code == 201, created.text
        material = created.json()["data"]
        assert material["status"] == "active" and material["version"] == "v1"

        bad = client.post(
            "/api/v1/impact/materials",
            headers=h,
            json={"name": "坏id", "product_type": "fund", "material_type": "海报",
                  "document_id": "../etc/passwd"},
        )
        # schema 白名单拒绝非法 document_id；全局处理器把 RequestValidationError
        # 统一映射为 400/code 1001（见 src/api/main.py validation_error_handler）
        assert bad.status_code == 400
        assert bad.json()["code"] == 1001

        patched = client.patch(
            f"/api/v1/impact/materials/{material['id']}",
            headers=h,
            json={"status": "archived", "owner": "归档人"},
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["status"] == "archived"

        assert client.patch(
            f"/api/v1/impact/materials/{material['id']}", headers=h, json={}
        ).status_code == 400
        assert client.patch(
            "/api/v1/impact/materials/999999999", headers=h, json={"owner": "x"}
        ).status_code == 404
    finally:
        db.query(ProductMaterial).filter_by(name="台账测试材料").delete()
        db.commit()
        reset_demo(db)
        db.close()
