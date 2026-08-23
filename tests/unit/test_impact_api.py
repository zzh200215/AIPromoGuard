"""法规影响中心 API 测试：分析 → 确认（沉淀关联）→ 一键批量复审 → 溯源。"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import (
    Article,
    ImpactAssessment,
    PenaltyCase,
    ProductMaterial,
    Regulation,
    RegulationUpdate,
    Rule,
    RuleRegulationLink,
)

client = TestClient(app)

_CHAIN_TITLE = "接口链路测试专用监管通知丙丁条款"
_KEYWORD_RULE = "丙丁产品风险揭示测试规则"


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


def _seed(db) -> tuple[int, int]:
    reg = Regulation(domain="fund", regulation_name="接口测试办法")
    db.add(reg)
    db.flush()
    db.add(Article(regulation_id=reg.id, content="宣传不得丙丁夸大"))
    linked_rule = Rule(
        domain="fund",
        rule_name="禁止丙丁条款夸大表述",
        rule_type="regex",
        rule_content={"pattern": "丙丁"},
        severity="medium",
    )
    db.add(linked_rule)
    db.flush()
    db.add(RuleRegulationLink(rule_id=linked_rule.id, regulation_id=reg.id))
    db.add(
        Rule(
            domain="fund",
            rule_name=_KEYWORD_RULE,
            rule_type="keyword",
            rule_content={"keywords": ["丙丁"]},
            severity="high",
        )
    )
    db.add(PenaltyCase(case_name="接口测试罚单", related_regulations=[reg.id]))
    upd = RegulationUpdate(
        source="csrc",
        title=_CHAIN_TITLE,
        status="imported",
        domain="fund",
        matched_regulations=[
            {"regulation_id": reg.id, "regulation_name": reg.regulation_name,
             "article_no": "", "status": "effective"}
        ],
    )
    db.add(upd)
    db.commit()
    return reg.id, upd.id


def _cleanup(db, regulation_id: int, update_id: int, material_ids: list[int]) -> None:
    db.query(ImpactAssessment).filter(
        ImpactAssessment.regulation_update_id == update_id
    ).delete(synchronize_session=False)
    db.query(RuleRegulationLink).filter(RuleRegulationLink.regulation_id == regulation_id).delete(
        synchronize_session=False
    )
    db.query(RegulationUpdate).filter_by(id=update_id).delete()
    db.query(PenaltyCase).filter(PenaltyCase.case_name == "接口测试罚单").delete()
    if material_ids:
        db.query(ProductMaterial).filter(ProductMaterial.id.in_(material_ids)).delete(
            synchronize_session=False
        )
    db.query(Rule).filter(
        Rule.rule_name.in_(["禁止丙丁条款夸大表述", _KEYWORD_RULE])
    ).delete(synchronize_session=False)
    db.query(Regulation).filter_by(id=regulation_id).delete()
    db.commit()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_impact_full_flow():
    db = SessionLocal()
    material_ids: list[int] = []
    regulation_id = update_id = 0
    try:
        regulation_id, update_id = _seed(db)
        h = _admin_headers()

        # 材料文档走真实上传，document_id 由服务端生成
        upload = client.post(
            "/api/v1/documents/upload",
            headers=h,
            files={
                "file": (
                    "接口测试材料.txt",
                    io.BytesIO("本产品丙丁保本".encode()),
                    "text/plain",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        document_id = upload.json()["data"]["document_id"]
        material = ProductMaterial(
            name="接口测试高风险材料",
            product_type="fund",
            material_type="宣传单页",
            document_id=document_id,
            last_review_status="violation",
        )
        db.add(material)
        db.commit()
        material_ids = [material.id]

        # 1. 触发分析
        r = client.post("/api/v1/impact/assessments", headers=h,
                        json={"regulation_update_id": update_id})
        assert r.status_code == 201, r.text
        assessment = r.json()["data"]
        assert assessment["status"] == "draft"
        assert any(x["matched_by"] == "link" for x in assessment["items"]["rules"])
        assert any(x["matched_by"] == "keyword" for x in assessment["items"]["rules"])
        aid = assessment["id"]

        # 2. 未确认前不能建复审批次
        r = client.post(f"/api/v1/impact/assessments/{aid}/batch", headers=h, json={})
        assert r.status_code == 400

        # 3. 确认影响：关键词命中的规则沉淀为结构化关联
        r = client.post(f"/api/v1/impact/assessments/{aid}/confirm", headers=h,
                        json={"action": "confirm"})
        assert r.status_code == 200, r.text
        confirmed = r.json()["data"]
        assert confirmed["status"] == "confirmed"
        assert confirmed["created_links"] >= 1
        link_count = (
            db.query(RuleRegulationLink)
            .filter(RuleRegulationLink.regulation_id == regulation_id)
            .count()
        )
        assert link_count == 2  # 种子 1 条 + 沉淀 1 条

        # 4. 一键批量复审：默认圈选已确认高/中风险且能定位文档的材料
        r = client.post(f"/api/v1/impact/assessments/{aid}/batch", headers=h, json={})
        assert r.status_code == 201, r.text
        batch = r.json()["data"]
        assert batch["total_count"] == 1 and len(batch["task_ids"]) == 1

        # 5. 详情含溯源批次与监管事件信息；批次本身带 source 溯源
        r = client.get(f"/api/v1/impact/assessments/{aid}", headers=h)
        assert r.status_code == 200
        detail = r.json()["data"]
        assert detail["batches"][0]["id"] == batch["batch_id"]
        assert detail["update"]["title"] == _CHAIN_TITLE

        listed = client.get("/api/v1/impact/assessments", headers=h).json()["data"]
        assert any(item["id"] == aid for item in listed["items"])
        assert any(
            item.get("source_type") == "impact_assessment"
            for item in client.get("/api/v1/batches", headers=h).json()["data"]["items"]
        )

        # 6. 重复确认被拒
        r = client.post(f"/api/v1/impact/assessments/{aid}/confirm", headers=h,
                        json={"action": "confirm"})
        assert r.status_code == 400
    finally:
        _cleanup(db, regulation_id, update_id, material_ids)
        db.close()
