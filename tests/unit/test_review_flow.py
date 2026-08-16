"""人工复核 + 报告下载集成测试：登录→上传→建任务→完成→列结果→确认。

依赖真实 DB 与审查工作流，DB 不可用或规则库为空时跳过。

方向④数据卫生：本测试真实写入共享开发库（建任务/审查/人工复核），
结束后在 finally 自清理 DB 记录与上传文件，避免污染 feedback 统计与规则精调建议
（此前 task 233 泄漏了一条"[复核] 测试人工复核"，就是本测试的残留）。
"""

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewResult, ReviewTask
from src.utils.config import settings

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import Rule

        db = SessionLocal()
        n = db.query(Rule).count()
        db.close()
        return n > 0
    except Exception:
        return False


def _cleanup_leak(task_id: int | None, doc_id: str | None, file_name: str | None) -> None:
    """测试结束清理：DB 的 task + review_results、磁盘上传文件。task_id 为 None 时跳过。"""
    db = SessionLocal()
    try:
        if task_id:
            db.query(ReviewResult).filter(ReviewResult.task_id == task_id).delete()
            db.query(ReviewTask).filter(ReviewTask.id == task_id).delete()
            db.commit()
    finally:
        db.close()
    if doc_id and file_name:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "txt"
        p = Path(settings.upload_dir) / f"{doc_id}.{ext}"
        if p.exists():
            p.unlink()


@pytest.mark.skipif(not _db_ready(), reason="数据库或规则库不可用")
def test_review_confirm_and_download_flow():
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sample = "本理财产品保本保收益，零风险，预期年化收益率5.8%，本金无忧。"
    up = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("复核测试.txt", io.BytesIO(sample.encode("utf-8")), "text/plain")},
    )
    assert up.status_code == 201
    up_data = up.json()["data"]
    doc_id, file_name = up_data["document_id"], up_data["file_name"]
    task_id: int | None = None

    try:
        created = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"document_id": doc_id, "document_type": "product_brochure"},
        )
        assert created.status_code == 201
        task_id = created.json()["data"]["task_id"]

        for _ in range(40):
            time.sleep(1)
            st = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["data"]["status"]
            if st in ("completed", "failed"):
                break
        assert st == "completed"

        # W14：任务详情返回各 Agent 节点耗时（PRD §11.3）
        detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["data"]
        stages = detail.get("stages") or {}
        assert {"classify", "regulation_match", "rule_scan", "llm_scan",
                "conflict_resolve", "risk_assess", "report"} <= set(stages.keys())
        assert all(s.get("status") == "completed" for s in stages.values())

        results = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers)
        assert results.status_code == 200
        items = results.json()["data"]["items"]
        assert len(items) > 0
        result_id = items[0]["result_id"]

        confirm = client.post(
            f"/api/v1/results/{result_id}/confirm",
            headers=headers,
            json={"verdict": "false_positive", "note": "测试人工复核"},
        )
        assert confirm.status_code == 200
        assert confirm.json()["data"]["status"] == "false_positive"

        dl = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=headers)
        assert dl.status_code == 200
        assert "金融产品合规审查报告" in dl.text

        dl_pdf = client.get(
            f"/api/v1/tasks/{task_id}/report/download?format=pdf", headers=headers
        )
        assert dl_pdf.status_code == 200
        assert dl_pdf.content[:4] == b"%PDF"
    finally:
        _cleanup_leak(task_id, doc_id, file_name)
