"""演示链路端到端测试：种子 → 分析 → 确认 → 一键复审 → 溯源，锁定固定案例不回退。"""

import pytest
from fastapi.testclient import TestClient
from scripts.demo.seed_impact_demo import reset_demo, seed_demo
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal

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
def test_demo_full_chain(isolated_materials):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        h = _admin_headers()

        # 1. 分析影响：2 条链接规则，10 份材料，3 高 / 3 中 / 4 低
        r = client.post(
            "/api/v1/impact/assessments", headers=h,
            json={"regulation_update_id": ids["regulation_update_id"]},
        )
        assert r.status_code == 201, r.text
        a = r.json()["data"]
        assert a["high_count"] == 3 and a["medium_count"] == 3 and a["low_count"] == 4
        materials = a["items"]["materials"]
        assert len(materials) == 10
        assert [m["risk_level"] for m in materials[:3]] == ["high"] * 3  # 按分数降序
        assert materials[0]["risk_score"] == 6  # high 规则 3 + 违规历史 2 + 罚单 1
        linked = [x for x in a["items"]["rules"] if x["matched_by"] == "link"]
        assert {x["rule_id"] for x in linked} == set(ids["rule_ids"])
        assert any("规则预扫命中" in m["reason"] for m in materials)

        # 2. 确认影响 → 3. 一键批量复审（默认圈选高/中风险 = 6 份）
        aid = a["id"]
        r = client.post(f"/api/v1/impact/assessments/{aid}/confirm", headers=h,
                        json={"action": "confirm"})
        assert r.status_code == 200
        r = client.post(f"/api/v1/impact/assessments/{aid}/batch", headers=h, json={})
        assert r.status_code == 201, r.text
        batch = r.json()["data"]
        assert batch["total_count"] == 6 and len(batch["task_ids"]) == 6

        # 4. 详情可溯源到复审批次
        detail = client.get(f"/api/v1/impact/assessments/{aid}", headers=h).json()["data"]
        assert detail["batches"][0]["id"] == batch["batch_id"]

        # 5. 种子可重放：重建后再次分析结果一致
        ids2 = seed_demo(db)
        assert ids2["regulation_update_id"] != ids["regulation_update_id"]  # 旧情报已随 reset 删除
        r = client.post(
            "/api/v1/impact/assessments", headers=h,
            json={"regulation_update_id": ids2["regulation_update_id"]},
        )
        a2 = r.json()["data"]
        assert (a2["high_count"], a2["medium_count"], a2["low_count"]) == (3, 3, 4)
    finally:
        reset_demo(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_impact_overview_counts(isolated_materials):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        h = _admin_headers()

        before = client.get("/api/v1/impact/overview", headers=h).json()["data"]
        assert before["updates_to_analyze"] >= 1  # 演示情报待分析
        assert before["pending_assessments"] == 0

        client.post(
            "/api/v1/impact/assessments", headers=h,
            json={"regulation_update_id": ids["regulation_update_id"]},
        )
        after = client.get("/api/v1/impact/overview", headers=h).json()["data"]
        assert after["updates_to_analyze"] == before["updates_to_analyze"] - 1
        assert after["pending_assessments"] == before["pending_assessments"] + 1
        assert after["high_risk_materials"] >= 3  # 演示案例 3 份高风险
        assert after["active_rules"] >= 2
    finally:
        reset_demo(db)
        db.close()
