"""法规溯源测试：违规落库时按规则反查结构化法条（regulation_id/article_id）。

- 关联带 article_id → 直接使用（最精确）；
- 关联只到法规 → 二元组重叠启发式挑最相关条款（确定性，无 LLM）；
- 无关联 / 无 rule_id → 两列为空；
- /tasks/{id}/results 响应带出 regulation_name / article_no 供复核界面展示。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import (
    Article,
    Regulation,
    ReviewResult,
    ReviewTask,
    Rule,
    RuleRegulationLink,
)
from src.services.review_service import _persist_results

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


@pytest.fixture()
def citation_env():
    """建一套 法规/条款/规则/关联 测试数据，用例结束清理。"""
    db = SessionLocal()
    reg = Regulation(domain="fund", regulation_name="溯源测试办法")
    db.add(reg)
    db.flush()
    art_hit = Article(
        regulation_id=reg.id, article_no="第一条", content="宣传材料不得使用保本保收益的表述"
    )
    art_other = Article(
        regulation_id=reg.id, article_no="第二条", content="基金销售机构应当披露费率信息"
    )
    db.add_all([art_hit, art_other])
    db.flush()
    _dsl = {
        "operator": "OR",
        "conditions": [{"type": "keyword", "keywords": ["溯源甲"], "match_mode": "any"}],
    }
    rule_precise = Rule(
        domain="fund", rule_name="溯源测试规则-精确", rule_type="keyword", rule_content=_dsl
    )
    rule_vague = Rule(
        domain="fund", rule_name="溯源测试规则-模糊", rule_type="keyword", rule_content=_dsl
    )
    db.add_all([rule_precise, rule_vague])
    db.flush()
    db.add_all(
        [
            RuleRegulationLink(
                rule_id=rule_precise.id,
                regulation_id=reg.id,
                article_id=art_hit.id,
                citation="精确关联",
            ),
            RuleRegulationLink(rule_id=rule_vague.id, regulation_id=reg.id),
        ]
    )
    task = ReviewTask(task_name="溯源测试任务", document_name="x.txt", status="completed")
    db.add(task)
    db.commit()
    ids = {
        "regulation": reg.id,
        "article_hit": art_hit.id,
        "article_other": art_other.id,
        "rule_precise": rule_precise.id,
        "rule_vague": rule_vague.id,
        "task": task.id,
    }
    yield ids
    db.query(ReviewResult).filter(ReviewResult.task_id == task.id).delete()
    db.query(RuleRegulationLink).filter(
        RuleRegulationLink.rule_id.in_([rule_precise.id, rule_vague.id])
    ).delete()
    db.query(Rule).filter(Rule.id.in_([rule_precise.id, rule_vague.id])).delete()
    db.query(Article).filter(Article.regulation_id == reg.id).delete()
    db.query(Regulation).filter(Regulation.id == reg.id).delete()
    db.commit()
    db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_citation_backfill(citation_env):
    ids = citation_env
    db = SessionLocal()
    try:
        findings = [
            {  # 精确关联（link 带 article_id）
                "violation_type": "rule",
                "risk_level": "high",
                "original_text": "保本保收益",
                "rule_id": ids["rule_precise"],
                "confidence": 0.95,
            },
            {  # 关联只到法规 → 启发式应挑中"保本"条款而非费率条款
                "violation_type": "rule",
                "risk_level": "medium",
                "original_text": "本产品保本无风险",
                "description": "涉嫌保本宣传",
                "rule_id": ids["rule_vague"],
                "confidence": 0.9,
            },
            {  # 无 rule_id → 无溯源
                "violation_type": "llm",
                "risk_level": "low",
                "original_text": "其他表述",
                "confidence": 0.6,
            },
        ]
        _persist_results(db, ids["task"], findings)
        db.commit()  # _persist_results 只入会话，提交由调用方负责

        rows = (
            db.query(ReviewResult)
            .filter(ReviewResult.task_id == ids["task"])
            .order_by(ReviewResult.id.asc())
            .all()
        )
        assert len(rows) == 3
        assert rows[0].regulation_id == ids["regulation"]
        assert rows[0].article_id == ids["article_hit"]
        assert rows[1].regulation_id == ids["regulation"]
        assert rows[1].article_id == ids["article_hit"]  # 重叠启发式命中保本条款
        assert rows[2].regulation_id is None and rows[2].article_id is None

        # API 带出展示字段
        h = _admin_headers()
        r = client.get(f"/api/v1/tasks/{ids['task']}/results", headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert items[0]["regulation_name"] == "溯源测试办法"
        assert items[0]["article_no"] == "第一条"
        assert "保本" in items[0]["article_excerpt"]
        assert items[2]["regulation_name"] is None
    finally:
        db.close()
