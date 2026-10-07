"""W17/W18 测试：人工反馈闭环统计 + 规则置信度阈值过滤。"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import AuditLog, ReviewResult, Rule, User

client = TestClient(app)


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.query(Rule).count()
        db.close()
        return True
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_feedback_stats_ok():
    r = client.get("/api/v1/results/feedback-stats", headers=_admin_headers())
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data["totals"].keys()) == {"pending_confirm", "confirmed", "false_positive"}
    assert set(data["by_source"].keys()) <= {"rule", "llm", "hybrid"}
    assert "overall_false_positive_rate" in data


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_rules_quality_ok():
    r = client.get("/api/v1/results/rules/quality", headers=_admin_headers())
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    # 按误报率降序
    rates = [i["false_positive_rate"] for i in items]
    assert rates == sorted(rates, reverse=True)
    if items:
        assert {"rule_id", "rule_name", "false_positive_rate", "confirm_rate"} <= set(
            items[0].keys()
        )


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_rule_scan_confidence_filter(monkeypatch):
    """W18：min_confidence 高于 keyword matcher(0.85) 时过滤 keyword 命中。"""
    from types import SimpleNamespace

    from src.core.agents.nodes.rule_scan import rule_scan

    db = SessionLocal()
    rule = Rule(
        domain="banking",
        rule_name="测试低置信规则",
        rule_type="keyword",
        rule_content={
            "operator": "OR",
            "conditions": [
                {
                    "type": "keyword",
                    "keywords": ["测试敏感词"],
                    "match_mode": "any",
                    "context_window": 10,
                }
            ],
        },
        severity="medium",
        description="测试用",
    )
    db.add(rule)
    db.commit()
    rid = rule.id
    try:
        state = {
            "domain": "banking",
            "blocks": [{"text": "文档包含测试敏感词", "page": 1, "paragraph": 1}],
        }

        def fake(threshold):
            s = SimpleNamespace()
            s.app_config = lambda section: (
                {"min_confidence": threshold} if section == "rule_engine" else {}
            )
            return s

        # 阈值 0.9 > keyword 置信度 0.85 → 命中被过滤
        monkeypatch.setattr("src.core.agents.nodes.rule_scan.settings", fake(0.9))
        out = rule_scan(state)
        assert all(h["rule_id"] != rid for h in out["rule_hits"])

        # 阈值 0.5 → 命中保留
        monkeypatch.setattr("src.core.agents.nodes.rule_scan.settings", fake(0.5))
        out = rule_scan(state)
        assert any(h["rule_id"] == rid for h in out["rule_hits"])
    finally:
        db.delete(rule)
        db.commit()
        db.close()


# ---------- 方向②：自动确认不计入人工反馈统计 + 翻案 ----------

def _admin_id() -> int:
    db = SessionLocal()
    uid = db.query(User).filter(User.username == "admin").first().id
    db.close()
    return uid


def _ensure_task_9876001() -> None:
    """confirm 端点会校验 result 所属 task 存在（否则 404），补建关联任务行。

    此前该测试隐式依赖开发库中恰好残留 id=9876001 的任务行，被 conftest
    清理逻辑删掉后即 404——改为测试自建数据，不再依赖外部状态。
    """
    from src.models import ReviewTask

    db = SessionLocal()
    try:
        if db.get(ReviewTask, 9876001) is None:
            db.add(
                ReviewTask(
                    id=9876001,
                    task_name="反馈统计测试任务",
                    document_name="反馈统计测试.txt",
                    document_path="/tmp/反馈统计测试.txt",
                    document_type="txt",
                    status="completed",
                    created_by=_admin_id(),
                )
            )
            db.commit()
    finally:
        db.close()


def _mk_result(vtype: str, status: str, confirmed_by: int | None) -> ReviewResult:
    return ReviewResult(
        task_id=9876001,
        violation_type=vtype,
        risk_level="medium",
        original_text=f"统计测试 {vtype} {status}",
        status=status,
        confirmed_by=confirmed_by,
    )


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_feedback_stats_excludes_auto_confirmed():
    """方向②：自动确认（confirmed_by=0）不计入反馈统计，只统计人工复核。"""
    db = SessionLocal()
    admin = _admin_id()
    try:
        db.query(ReviewResult).filter(ReviewResult.task_id == 9876001).delete()
        db.commit()
        headers = _admin_headers()
        base = client.get("/api/v1/results/feedback-stats", headers=headers).json()["data"]
        base = base["totals"]
        rows = [
            _mk_result("rule", "confirmed", 0),  # 自动确认，应被排除
            _mk_result("rule", "confirmed", admin),
            _mk_result("llm", "false_positive", admin),
        ]
        db.add_all(rows)
        db.commit()
        r = client.get("/api/v1/results/feedback-stats", headers=headers)
        assert r.status_code == 200
        totals = r.json()["data"]["totals"]
        assert totals["confirmed"] == base["confirmed"] + 1  # 只计入人工确认那条
        assert totals["false_positive"] == base["false_positive"] + 1
        assert totals["pending_confirm"] == base["pending_confirm"]
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == 9876001).delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_confirm_overturn_auto_confirmed():
    """方向②：自动确认结果可被人工翻案为误报，翻案后计入人工统计。"""
    _ensure_task_9876001()
    db = SessionLocal()
    admin = _admin_id()
    result = _mk_result("rule", "confirmed", 0)
    db.add(result)
    db.commit()
    result_id = result.id  # commit 后 id 已生成
    try:
        headers = _admin_headers()
        base = client.get("/api/v1/results/feedback-stats", headers=headers).json()["data"]
        base_fp = base["totals"]["false_positive"]
        base_rule_fp = base["by_source"].get("rule", {}).get("false_positive", 0)

        r = client.post(
            f"/api/v1/results/{result_id}/confirm",
            headers=headers,
            json={"verdict": "false_positive", "note": "翻案测试"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "false_positive"
        assert data["confirmed_by"] == admin
        assert data["auto_confirmed"] is False

        # MySQL REPEATABLE READ：结束本 session 快照事务再读，才能看到 API 的提交
        db.rollback()
        db.refresh(result)
        assert result.status == "false_positive"
        assert result.confirmed_by == admin

        # 翻案后进入人工反馈统计
        stats = client.get("/api/v1/results/feedback-stats", headers=headers).json()["data"]
        assert stats["totals"]["false_positive"] == base_fp + 1
        assert stats["by_source"]["rule"]["false_positive"] == base_rule_fp + 1
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == 9876001).delete()
        # confirm 端点现在会写判定审计（result.confirm），测试数据按约定自清理
        db.query(AuditLog).filter(
            AuditLog.action == "result.confirm",
            AuditLog.resource_id == str(result_id),
        ).delete(synchronize_session=False)
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_confirm_writes_audit_trail():
    """判定留痕：confirm 写入带前后状态的审计行（采纳率报告的翻案口径数据源）。"""
    import json as _json

    _ensure_task_9876001()
    db = SessionLocal()
    result = _mk_result("rule", "confirmed", 0)  # 自动确认结果被人工翻案
    db.add(result)
    db.commit()
    result_id = result.id
    try:
        r = client.post(
            f"/api/v1/results/{result_id}/confirm",
            headers=_admin_headers(),
            json={"verdict": "false_positive"},
        )
        assert r.status_code == 200
        db.rollback()  # 结束快照事务再读（REPEATABLE READ）
        row = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "result.confirm",
                AuditLog.resource_id == str(result_id),
            )
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None
        detail = _json.loads(row.detail)
        assert isinstance(detail.get("task_id"), int)  # 结论删除后可归属回任务
        assert detail["before_status"] == "confirmed"
        assert detail["before_auto_confirmed"] is True
        assert detail["verdict"] == "false_positive"
    finally:
        db.query(ReviewResult).filter(ReviewResult.task_id == 9876001).delete()
        db.query(AuditLog).filter(
            AuditLog.action == "result.confirm",
            AuditLog.resource_id == str(result_id),
        ).delete(synchronize_session=False)
        db.commit()
        db.close()
