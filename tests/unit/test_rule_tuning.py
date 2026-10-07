"""方向③规则精调测试：建议生成阈值/动作分级/误报关键词提取 + apply 逻辑。

依赖真实 DB（skipif）：构造 Rule + 人工复核的 ReviewResult，验证建议生成与应用。
"""

import pytest
from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewResult, Rule
from src.services.rule_tuning import (
    apply_suggestion,
    build_rule_suggestions,
    compute_threshold_suggestion,
)
from src.utils.errors import AppError

_TASK = 9877000  # 测试专用 task_id，finally 按此清理


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _mk_rule(db, keywords: list[str], is_active: int = 1) -> Rule:
    rule = Rule(
        domain="banking",
        rule_name=f"测试规则{keywords[0] if keywords else 'x'}",
        rule_type="keyword",
        rule_content={
            "operator": "OR",
            "conditions": [
                {
                    "type": "keyword",
                    "keywords": list(keywords),
                    "match_mode": "any",
                    "context_window": 15,
                    "negation_window": 8,
                }
            ],
        },
        severity="medium",
        is_active=is_active,
    )
    db.add(rule)
    db.commit()
    return rule


def _mk_result(db, rule_id: int, status: str, text: str, confidence: float = 0.85) -> None:
    db.add(
        ReviewResult(
            task_id=_TASK,
            violation_type="rule",
            risk_level="medium",
            original_text=text,
            rule_id=rule_id,
            status=status,
            confirmed_by=1,  # 人工复核（>0 才计入统计）
            confidence_score=confidence,
        )
    )
    db.commit()


def _cleanup(db):
    db.query(ReviewResult).filter(ReviewResult.task_id == _TASK).delete()
    db.query(Rule).filter(Rule.rule_name.like("测试规则%")).delete()
    db.commit()


# ---------- build_rule_suggestions ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_no_suggestion_below_min_samples():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "false_positive", "承诺保本")  # 仅 1 条复核 < min_samples
        sugs = build_rule_suggestions(db)
        assert all(s["rule_id"] != rule.id for s in sugs)  # 本规则不出建议
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_no_suggestion_below_fp_threshold():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "confirmed", "保本保收益违规")
        _mk_result(db, rule.id, "confirmed", "承诺保本收益")
        _mk_result(db, rule.id, "false_positive", "本产品不保本")  # 误报率 1/3 < 0.5
        sugs = build_rule_suggestions(db)
        assert all(s["rule_id"] != rule.id for s in sugs)
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_deactivate_pure_fp():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "false_positive", "承诺保本")
        _mk_result(db, rule.id, "false_positive", "保本宣传")
        _mk_result(db, rule.id, "false_positive", "保本理财")
        sugs = [s for s in build_rule_suggestions(db) if s["rule_id"] == rule.id]
        assert len(sugs) == 1
        assert sugs[0]["action"] == "deactivate"
        assert sugs[0]["confirmed"] == 0 and sugs[0]["false_positive"] == 3
        assert sugs[0]["fp_rate"] == 1.0
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_remove_keyword_suggestion():
    """部分误报：关键词「保本」误报 2 次、从未确认 → 建议移除。"""
    db = SessionLocal()
    rule = _mk_rule(db, ["保本", "保收益"])
    try:
        _mk_result(db, rule.id, "false_positive", "本产品承诺保本")
        _mk_result(db, rule.id, "false_positive", "保本理财不是存款")
        _mk_result(db, rule.id, "confirmed", "违规承诺保收益")  # 确认命中「保收益」，保本确认 0 次
        sugs = [s for s in build_rule_suggestions(db) if s["rule_id"] == rule.id]
        assert len(sugs) == 1
        sug = sugs[0]
        assert sug["action"] == "remove_keyword"
        assert sug["keyword"] == "保本"
        assert sug["condition_index"] == 0
        assert "从未被确认" in sug["reason"]
        assert len(sug["fp_samples"]) == 2
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_no_remove_keyword_when_confirmed():
    """关键词被确认过（conf_hits>0）即使误报多也不建议移除。"""
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "false_positive", "本产品承诺保本")
        _mk_result(db, rule.id, "false_positive", "保本理财不是存款")
        _mk_result(db, rule.id, "confirmed", "违规承诺保本")  # 确认也命中「保本」
        sugs = build_rule_suggestions(db)
        assert all(s["rule_id"] != rule.id for s in sugs)
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_inactive_rule_skipped():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"], is_active=0)
    try:
        _mk_result(db, rule.id, "false_positive", "承诺保本")
        _mk_result(db, rule.id, "false_positive", "保本宣传")
        _mk_result(db, rule.id, "false_positive", "保本理财")
        sugs = build_rule_suggestions(db)
        assert all(s["rule_id"] != rule.id for s in sugs)
    finally:
        _cleanup(db)
        db.close()


# ---------- compute_threshold_suggestion（纯函数） ----------

def test_threshold_suggestion_clean_split():
    """确认≥0.95 / 误报≤0.85 → 可分离阈值 0.90（全保确认、全滤误报）。"""
    assert compute_threshold_suggestion([0.95], [0.85]) == (0.90, True)
    assert compute_threshold_suggestion([0.95, 0.95], [0.85]) == (0.90, True)
    assert compute_threshold_suggestion([0.93], [0.87]) == (0.90, True)


def test_threshold_suggestion_no_split():
    """分布重叠/无误报 → 不给出阈值建议（避免盲目抬阈值）。"""
    assert compute_threshold_suggestion([0.85], [0.95]) is None  # FP 置信度更高
    assert compute_threshold_suggestion([0.85], [0.85]) is None  # 完全重叠
    assert compute_threshold_suggestion([0.95], []) is None      # 无误报可滤
    assert compute_threshold_suggestion([], [0.85]) is None      # 无确认样本可比


# ---------- apply_suggestion ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_apply_deactivate():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    v0 = rule.version
    try:
        updated = apply_suggestion(db, rule.id, "deactivate")
        assert updated.is_active == 0
        assert updated.version == v0 + 1
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_apply_remove_keyword():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本", "保收益"])
    v0 = rule.version
    try:
        updated = apply_suggestion(db, rule.id, "remove_keyword", condition_index=0, keyword="保本")
        cond = updated.rule_content["conditions"][0]
        assert cond["keywords"] == ["保收益"]
        assert updated.version == v0 + 1
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_apply_errors():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        with pytest.raises(AppError):
            apply_suggestion(db, 999999, "deactivate")  # 规则不存在
        with pytest.raises(AppError):
            apply_suggestion(db, rule.id, "unknown_action")  # 非法 action
        with pytest.raises(AppError):
            apply_suggestion(db, rule.id, "remove_keyword")  # 缺 keyword
        with pytest.raises(AppError):
            apply_suggestion(db, rule.id, "remove_keyword", condition_index=0, keyword="不存在的词")
        with pytest.raises(AppError):
            apply_suggestion(db, rule.id, "set_threshold")  # 缺 threshold
        with pytest.raises(AppError):
            apply_suggestion(db, rule.id, "set_threshold", threshold=0.1)  # 阈值越界
    finally:
        _cleanup(db)
        db.close()


# ---------- set_threshold（调阈值杠杆） ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_set_threshold_suggestion():
    """确认(≥0.95) 与误报(≤0.85) 置信度可分 → 建议抬该规则阈值到 0.90。"""
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "confirmed", "违规承诺保本", confidence=0.95)
        _mk_result(db, rule.id, "confirmed", "保本承诺是违法的", confidence=0.95)
        _mk_result(db, rule.id, "false_positive", "本产品不保本", confidence=0.85)
        _mk_result(db, rule.id, "false_positive", "保本宣传违规了吗", confidence=0.85)
        sugs = [s for s in build_rule_suggestions(db) if s["rule_id"] == rule.id]
        assert len(sugs) == 1
        sug = sugs[0]
        assert sug["action"] == "set_threshold"
        assert sug["threshold"] == 0.90
        assert "调阈值" in sug["reason"] or "min_confidence" in sug["reason"]
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_no_set_threshold_when_no_split():
    """确认/误报置信度重叠（同为 0.85）→ 无阈值建议，交由其他 heuristics。"""
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    try:
        _mk_result(db, rule.id, "confirmed", "违规承诺保本", confidence=0.85)
        _mk_result(db, rule.id, "confirmed", "保本承诺违法", confidence=0.85)
        _mk_result(db, rule.id, "false_positive", "本产品不保本", confidence=0.85)
        _mk_result(db, rule.id, "false_positive", "保本辩论", confidence=0.85)
        sugs = [s for s in build_rule_suggestions(db) if s["rule_id"] == rule.id]
        assert all(s["action"] != "set_threshold" for s in sugs)
    finally:
        _cleanup(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_apply_set_threshold():
    db = SessionLocal()
    rule = _mk_rule(db, ["保本"])
    v0 = rule.version
    try:
        updated = apply_suggestion(db, rule.id, "set_threshold", threshold=0.90)
        assert updated.rule_content["min_confidence"] == 0.90
        assert updated.version == v0 + 1
    finally:
        _cleanup(db)
        db.close()
