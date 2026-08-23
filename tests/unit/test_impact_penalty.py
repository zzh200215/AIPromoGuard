"""罚单驱动链路测试：罚单触发影响分析 + LLM 规则候选挖掘（草稿不生效）。"""

import json

import pytest
from scripts.demo.seed_impact_demo import DEMO_PENALTY, reset_demo, seed_demo
from sqlalchemy import text
from src.core.impact import analyze, mining
from src.core.impact.mining import mine_rule_candidates, parse_candidates
from src.infrastructure.database.mysql import SessionLocal
from src.models import PenaltyCase, Rule, RuleRegulationLink
from src.utils.errors import AppError


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


_FAKE_LLM_OUTPUT = json.dumps(
    [
        {
            "domain": "fund",
            "rule_name": "挖掘测试-禁止绝对收益承诺",
            "rule_type": "regex",
            "severity": "high",
            "pattern": "保证收益|收益无忧",
            "description": "依据：罚单认定的收益承诺违规",
        },
        {
            "domain": "bad_domain",
            "rule_name": "挖掘测试-限制历史业绩表述",
            "rule_type": "keyword",
            "severity": "ultra",
            "keywords": ["历史冠军", "业绩第一"],
        },
    ],
    ensure_ascii=False,
)


class _FakeLLM:
    def chat(self, messages: list[dict]) -> str:  # noqa: ARG002
        return _FAKE_LLM_OUTPUT


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_analyze_from_penalty_case(isolated_materials):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        case = db.query(PenaltyCase).filter_by(case_name=DEMO_PENALTY).one()

        assessment = analyze(db, penalty_case_id=case.id)
        assert assessment.penalty_case_id == case.id
        assert assessment.regulation_update_id is None
        assert assessment.status == "draft"
        linked = {
            entry["rule_id"]
            for entry in assessment.items["rules"]
            if entry["matched_by"] == "link"
        }
        assert set(ids["rule_ids"]) <= linked  # 罚单引用法规 → 结构化关联规则全部命中
        assert len(assessment.items["materials"]) == 10  # fund 域台账材料

        again = analyze(db, penalty_case_id=case.id)
        assert again.id == assessment.id  # 一个罚单一份评估

        with pytest.raises(AppError):
            analyze(db)  # 不传源
        with pytest.raises(AppError):
            analyze(db, regulation_update_id=ids["regulation_update_id"], penalty_case_id=case.id)
    finally:
        reset_demo(db)
        db.close()


def test_parse_candidates_tolerates_garbage():
    assert parse_candidates(None) == []
    assert parse_candidates("完全不是 JSON") == []
    assert parse_candidates("前置说明 [") == []
    wrapped = "```json\n" + _FAKE_LLM_OUTPUT + "\n```"
    parsed = parse_candidates(wrapped)
    assert len(parsed) == 2
    assert parsed[0]["rule_type"] == "regex" and parsed[0]["pattern"]
    assert parsed[1]["domain"] == "fund"  # 非法域回退
    assert parsed[1]["severity"] == "medium"  # 非法严重度回退
    assert parsed[1]["keywords"]


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_mine_rule_candidates_creates_drafts(monkeypatch):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        case = db.query(PenaltyCase).filter_by(case_name=DEMO_PENALTY).one()
        monkeypatch.setattr(mining, "get_llm", lambda: _FakeLLM())

        rules = mine_rule_candidates(db, case.id, created_by=1)
        assert len(rules) == 2
        for rule in rules:
            assert rule.status == "draft" and rule.is_active == 0  # 草稿不生效
            assert rule.rule_name.startswith("挖掘测试-")
        keyword_rule = next(r for r in rules if r.rule_type == "keyword")
        assert keyword_rule.domain == "fund" and keyword_rule.severity == "medium"

        links = (
            db.query(RuleRegulationLink)
            .filter(RuleRegulationLink.source == "penalty_mining")
            .all()
        )
        assert len(links) == 2
        assert all(link.regulation_id == ids["regulation_id"] for link in links)

        with pytest.raises(AppError):  # 同名规则已存在，重复挖掘无新增
            mine_rule_candidates(db, case.id)
    finally:
        db.query(RuleRegulationLink).filter(
            RuleRegulationLink.source == "penalty_mining"
        ).delete(synchronize_session=False)
        db.query(Rule).filter(Rule.rule_name.like("挖掘测试-%")).delete(
            synchronize_session=False
        )
        db.commit()
        reset_demo(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_mine_requires_llm(monkeypatch):
    db = SessionLocal()
    try:
        seed_demo(db)
        case = db.query(PenaltyCase).filter_by(case_name=DEMO_PENALTY).one()
        monkeypatch.setattr(mining, "get_llm", lambda: None)  # 未配 key
        with pytest.raises(AppError):
            mine_rule_candidates(db, case.id)
    finally:
        reset_demo(db)
        db.close()
