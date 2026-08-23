"""整改复测闭环测试：上传整改版 v2 → 单任务复测 → 通过后自动关闭原整改项。"""

import time

import pytest
from fastapi.testclient import TestClient
from scripts.demo.seed_impact_demo import _LOW_TEXT, _demo_dir, reset_demo, seed_demo
from sqlalchemy import text
from src.api.main import app
from src.core.impact import analyze
from src.core.impact.analysis import material_document_path
from src.infrastructure.database.mysql import SessionLocal
from src.models import ImpactAssessment, ProductMaterial, ReviewBatch, ReviewResult, ReviewTask
from src.services.impact_service import sync_batch_to_assessment

client = TestClient(app)
HIGH_DOC = "doc_5d6f7a01"  # 演示种子中的高违规材料
WAIT_TIMEOUT = 150


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


def _wait_retest_done(assessment_id: int, task_id: int, h: dict) -> dict:
    """轮询整改清单直到复测条目出现且到终态。"""
    deadline = time.time() + WAIT_TIMEOUT
    while time.time() < deadline:
        items = client.get(
            f"/api/v1/impact/assessments/{assessment_id}/remediation", headers=h
        ).json()["data"]["items"]
        entry = next((e for e in items if e["task_id"] == task_id), None)
        if entry and entry["task_status"] in ("completed", "failed"):
            return entry
        time.sleep(2)
    raise TimeoutError(f"复测任务 {task_id} 未在 {WAIT_TIMEOUT}s 内到终态")


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_retest_closes_remediation_loop(isolated_materials, monkeypatch):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        assessment = analyze(db, ids["regulation_update_id"])
        material = db.query(ProductMaterial).filter_by(document_id=HIGH_DOC).one()

        # 原复审批次：假完成态 + 1 条违规命中（走 sync 短路径，不起真实图）
        batch = ReviewBatch(
            batch_name="复测闭环测试批次",
            status="completed",
            total_count=1,
            completed_count=1,
            source_type="impact_assessment",
            source_id=assessment.id,
        )
        db.add(batch)
        db.flush()
        task = ReviewTask(
            task_name=material.name,
            document_name=f"{HIGH_DOC}.txt",
            document_path=str(_demo_dir() / f"{HIGH_DOC}.txt"),
            status="completed",
            batch_id=batch.id,
        )
        db.add(task)
        db.flush()
        db.add(
            ReviewResult(
                task_id=task.id,
                violation_type="rule",
                risk_level="high",
                original_text="保本无虞",
            )
        )
        db.commit()
        sync_batch_to_assessment(db, batch.id)

        h = _admin_headers()
        r = client.post(
            f"/api/v1/impact/assessments/{assessment.id}/confirm",
            headers=h,
            json={"action": "confirm"},  # 全量确认，满足复测的前置状态
        )
        assert r.status_code == 200, r.text
        items = client.get(
            f"/api/v1/impact/assessments/{assessment.id}/remediation", headers=h
        ).json()["data"]["items"]
        orig = next(e for e in items if e["task_id"] == task.id)
        assert orig["requires_remediation"] is True and orig["decision"] == "pending"

        # 上传整改版 v2（干净文本）→ 复测任务真实起跑；关 LLM 走纯规则引擎保证确定性
        import src.core.agents.nodes.llm_scan as llm_scan_mod

        monkeypatch.setattr(llm_scan_mod, "get_llm", lambda: None)
        r = client.post(
            f"/api/v1/impact/materials/{material.id}/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("整改版.txt", _LOW_TEXT.encode("utf-8"), "text/plain")},
        )
        assert r.status_code == 201, r.text
        started = r.json()["data"]
        assert started["version"] == "v2"
        retest_task_id = started["task_id"]

        retest_entry = _wait_retest_done(assessment.id, retest_task_id, h)
        assert retest_entry["retest"] is True
        assert retest_entry["retest_for_task_id"] == task.id
        assert retest_entry["violation_count"] == 0
        assert retest_entry["requires_remediation"] is False

        # 闭环：复测通过 → 原整改项自动 done，台账升版并回写 clean
        items = client.get(
            f"/api/v1/impact/assessments/{assessment.id}/remediation", headers=h
        ).json()["data"]["items"]
        orig_after = next(e for e in items if e["task_id"] == task.id)
        assert orig_after["retest_task_id"] == retest_task_id
        assert orig_after["decision"] == "done"

        db.rollback()
        db.expire_all()  # 空闲会话的 rollback 不使对象过期，identity map 仍是 API 写入前的旧值
        fresh = db.get(ProductMaterial, material.id)
        assert fresh.version == "v2"
        assert fresh.last_review_status == "clean"
        assert fresh.document_id == started["document_id"]

        # 已无待整改项，再次复测被拒
        again = client.post(
            f"/api/v1/impact/materials/{material.id}/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("再测.txt", _LOW_TEXT.encode("utf-8"), "text/plain")},
        )
        assert again.status_code == 400
    finally:
        started = locals().get("started")
        if started:  # 清理复测上传的真实文件
            path = material_document_path(started["document_id"])
            if path:
                path.unlink(missing_ok=True)
        reset_demo(db)
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_retest_validation(isolated_materials):
    db = SessionLocal()
    try:
        ids = seed_demo(db)
        assessment = analyze(db, ids["regulation_update_id"])  # draft，未确认
        material = db.query(ProductMaterial).filter_by(document_id=HIGH_DOC).one()
        h = _admin_headers()

        # 评估未确认 → 400
        r = client.post(
            f"/api/v1/impact/materials/{material.id}/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("整改版.txt", "内容".encode(), "text/plain")},
        )
        assert r.status_code == 400

        # 材料不存在 → 404；非法扩展名 → 400（文件格式不支持）
        r = client.post(
            "/api/v1/impact/materials/999999999/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("整改版.txt", "内容".encode(), "text/plain")},
        )
        assert r.status_code == 404
        confirmed = db.get(ImpactAssessment, assessment.id)
        confirmed.status = "confirmed"
        db.commit()
        r = client.post(
            f"/api/v1/impact/materials/{material.id}/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("整改版.exe", b"x", "application/octet-stream")},
        )
        assert r.status_code == 400 and r.json()["code"] == 1002

        # 已确认但无整改清单 → 400（文件应被回滚清理）
        r = client.post(
            f"/api/v1/impact/materials/{material.id}/retest",
            headers=h,
            data={"assessment_id": str(assessment.id)},
            files={"file": ("整改版.txt", "内容".encode(), "text/plain")},
        )
        assert r.status_code == 400 and "待整改" in r.json()["message"]
    finally:
        reset_demo(db)
        db.close()
