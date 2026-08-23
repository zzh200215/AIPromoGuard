"""法规影响分析模块测试：确定性打分/分词纯函数 + 全链路定位与幂等覆盖。"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.core.impact.analysis import (
    _DOMAIN_TO_PRODUCT,
    _score_material,
    _text_bigrams,
    analyze,
)
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
from src.utils.errors import AppError

# 合成词避免与种子规则库（销售/宣传/保本等高频词）意外关键词撞车，保证测试密闭
_CHAIN_TITLE = "影响分析链路测试专用监管通知量子条款"
_FALLBACK_TITLE = "量子玄机专项指引甲乙测试公告"


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def test_score_material_deterministic_levels():
    assert _score_material("high", "violation", 2) == (6, "high")
    assert _score_material("medium", "violation", 0) == (4, "high")
    assert _score_material("high", None, 0) == (3, "medium")
    assert _score_material("low", "clean", 1) == (2, "medium")
    assert _score_material("low", None, 0) == (1, "low")
    assert _score_material(None, None, 0) == (1, "low")


def test_text_bigrams_filters_stop_chars():
    grams = _text_bigrams("基金的销售")
    assert grams == {"基金", "销售"}
    assert _text_bigrams("") == set()
    assert _text_bigrams(None) == set()


def test_domain_product_mapping_covers_all_rule_domains():
    for domain in ("fund", "insurance", "banking"):
        assert domain in _DOMAIN_TO_PRODUCT


def _seed_chain(db: Session) -> RegulationUpdate:
    reg = Regulation(domain="fund", regulation_name="影响分析测试办法")
    db.add(reg)
    db.flush()
    db.add(Article(regulation_id=reg.id, content="宣传材料不得夸大"))
    rule = Rule(
        domain="fund",
        rule_name="禁止量子条款夸大表述",
        rule_type="regex",
        rule_content={"pattern": "量子"},
        severity="medium",
    )
    db.add(rule)
    db.flush()
    db.add(RuleRegulationLink(rule_id=rule.id, regulation_id=reg.id))
    db.add(
        ProductMaterial(
            name="链路高风险材料", product_type="fund",
            material_type="宣传单页", last_review_status="violation",
        )
    )
    db.add(
        ProductMaterial(
            name="链路干净材料", product_type="fund",
            material_type="海报", last_review_status="clean",
        )
    )
    db.add(PenaltyCase(case_name="链路测试罚单", related_regulations=[reg.id]))
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
    return upd


def _cleanup_chain(db: Session) -> None:
    db.query(ImpactAssessment).filter(
        ImpactAssessment.regulation_update_id.in_(
            db.query(RegulationUpdate.id).filter(
                RegulationUpdate.title.in_([_CHAIN_TITLE, _FALLBACK_TITLE])
            )
        )
    ).delete(synchronize_session=False)
    db.query(RuleRegulationLink).filter(
        RuleRegulationLink.rule_id.in_(
            db.query(Rule.id).filter(
                Rule.rule_name.in_(["禁止量子条款夸大表述", "量子玄机风险揭示甲乙测试规则"])
            )
        )
    ).delete(synchronize_session=False)
    db.query(PenaltyCase).filter(PenaltyCase.case_name == "链路测试罚单").delete()
    db.query(ProductMaterial).filter(
        ProductMaterial.name.in_(["链路高风险材料", "链路干净材料"])
    ).delete(synchronize_session=False)
    for title in (_CHAIN_TITLE, _FALLBACK_TITLE):
        upd = db.query(RegulationUpdate).filter_by(title=title).one_or_none()
        if upd is not None:
            db.query(Regulation).filter(
                Regulation.id.in_(
                    [m["regulation_id"] for m in (upd.matched_regulations or [])]
                )
            ).delete(synchronize_session=False)
            db.delete(upd)
    db.query(Rule).filter(
        Rule.rule_name.in_(["禁止量子条款夸大表述", "量子玄机风险揭示甲乙测试规则"])
    ).delete(synchronize_session=False)
    db.query(Article).filter(Article.content == "宣传材料不得夸大").delete()
    db.commit()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_analyze_full_chain_and_reanalyze_overwrites_draft(isolated_materials):
    db = SessionLocal()
    try:
        _cleanup_chain(db)
        upd = _seed_chain(db)
        assessment = analyze(db, upd.id)

        assert assessment.status == "draft"
        assert assessment.high_count == 1 and assessment.medium_count == 1
        materials = assessment.items["materials"]
        assert materials[0]["name"] == "链路高风险材料"
        assert materials[0]["risk_level"] == "high"  # 2+2+1
        assert materials[1]["risk_level"] == "medium"  # 2+0+1
        rules = assessment.items["rules"]
        assert len(rules) == 1 and rules[0]["matched_by"] == "link"
        assert "受影响材料2份（高1/中1/低0）" in assessment.summary
        assert "关联法规1部" in assessment.summary

        again = analyze(db, upd.id)
        assert again.id == assessment.id  # 一个事件一份评估
        assert again.status == "draft"
    finally:
        _cleanup_chain(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_analyze_keyword_fallback_without_links(isolated_materials):
    db = SessionLocal()
    try:
        _cleanup_chain(db)
        db.add(
            Rule(
                domain="fund",
                rule_name="量子玄机风险揭示甲乙测试规则",
                rule_type="keyword",
                rule_content={"keywords": ["量子"]},
                severity="high",
            )
        )
        upd = RegulationUpdate(source="nfra", title=_FALLBACK_TITLE, status="imported",
                               domain="fund", matched_regulations=[])
        db.add(upd)
        db.commit()

        assessment = analyze(db, upd.id)
        rules = assessment.items["rules"]
        assert any(
            r["rule_name"] == "量子玄机风险揭示甲乙测试规则" and r["matched_by"] == "keyword"
            for r in rules
        )
        assert assessment.items["materials"] == []  # 无材料台账命中该域
    finally:
        _cleanup_chain(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_analyze_preserves_non_draft_and_missing_raises():
    db = SessionLocal()
    try:
        _cleanup_chain(db)
        upd = _seed_chain(db)
        assessment = analyze(db, upd.id)
        assessment.status = "pending_review"
        assessment.items = None  # 人工流程中的数据不被重复分析覆盖
        db.commit()

        again = analyze(db, upd.id)
        assert again.id == assessment.id
        assert again.items is None and again.status == "pending_review"

        with pytest.raises(AppError):
            analyze(db, 999999999)
    finally:
        _cleanup_chain(db)
        db.close()
