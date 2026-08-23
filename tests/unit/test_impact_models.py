"""法规影响中心数据层测试：迁移幂等、表结构、ORM CRUD 与 JSON 明细回读。"""

import pytest
from scripts.migrate.impact_center import migrate as impact_migrate
from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal
from src.models import ImpactAssessment, ProductMaterial, ReviewBatch, Rule, RuleRegulationLink


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_migration_idempotent_and_tables_exist():
    impact_migrate()  # 已建过则全部跳过，不报错
    impact_migrate()
    db = SessionLocal()
    try:
        for table in ("rule_regulation_links", "product_materials", "impact_assessments"):
            rows = db.execute(
                text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ),
                {"t": table},
            ).fetchall()
            assert len(rows) == 1, f"缺表 {table}"
        rule_cols = _existing_columns(db, "rules")
        assert "status" in rule_cols
        batch_cols = _existing_columns(db, "review_batches")
        assert {"source_type", "source_id"} <= batch_cols
    finally:
        db.close()


def _existing_columns(db, table: str) -> set[str]:
    rows = db.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table},
    ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_models_crud_roundtrip():
    db = SessionLocal()
    try:
        rule = Rule(domain="fund", rule_name="影响中心测试规则", rule_type="regex",
                    rule_content={"pattern": "保本"})
        db.add(rule)
        db.flush()

        citation = "《公开募集证券投资基金销售机构监督管理办法》第X条"
        link = RuleRegulationLink(rule_id=rule.id, citation=citation)
        db.add(link)

        material = ProductMaterial(
            name="影响中心测试材料", product_type="fund", material_type="宣传单页"
        )
        db.add(material)
        db.flush()

        assessment = ImpactAssessment(
            title="影响中心测试评估",
            items={
                "rules": [{"rule_id": rule.id, "rule_name": rule.rule_name,
                           "reason": "规则指向该条款", "confirm_status": "pending"}],
                "materials": [{"material_id": material.id, "name": material.name,
                               "reason": "含保本表述", "risk_level": "high",
                               "confirm_status": "pending"}],
            },
            high_count=1,
        )
        db.add(assessment)
        batch = ReviewBatch(batch_name="影响中心测试批次", source_type="impact_assessment",
                            source_id=None)
        db.add(batch)
        db.commit()

        assert rule.status == "active"  # 存量规则默认即生效
        fetched_link = db.query(RuleRegulationLink).filter_by(rule_id=rule.id).one()
        assert fetched_link.source == "manual"
        fetched = db.get(ImpactAssessment, assessment.id)
        assert fetched.status == "draft"
        assert fetched.items["materials"][0]["risk_level"] == "high"
        assert fetched.high_count == 1 and fetched.medium_count == 0
        fetched_batch = db.query(ReviewBatch).filter_by(id=batch.id).one()
        assert fetched_batch.source_type == "impact_assessment"
    finally:
        db.rollback()
        db.query(RuleRegulationLink).filter_by(citation="《公开募集证券投资基金销售机构监督管理办法》第X条").delete()
        db.query(Rule).filter_by(rule_name="影响中心测试规则").delete()
        db.query(ImpactAssessment).filter_by(title="影响中心测试评估").delete()
        db.query(ProductMaterial).filter_by(name="影响中心测试材料").delete()
        db.query(ReviewBatch).filter_by(batch_name="影响中心测试批次").delete()
        db.commit()
        db.close()
