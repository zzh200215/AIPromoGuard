"""对比审查集成测试：创建对比任务→完成→报告含变更对照。

依赖真实 DB 与审查工作流，DB 不可用或规则库为空时跳过。
"""

import io
import time

import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

        db = SessionLocal()
        from src.models import Rule

        n = db.query(Rule).count()
        db.close()
        return n > 0
    except Exception:
        return False


def _admin_headers() -> dict:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


def _upload(headers, name, content):
    r = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content.encode()), "text/plain")},
    )
    return r.json()["data"]["document_id"]


def _wait_completed(headers, task_id) -> str:
    # 等待窗口 120s：真实审查流程含 LLM 节点（实测可达 60s 量级），
    # 原 40s 窗口会先于流程结束而误判 running
    for _ in range(120):
        time.sleep(1)
        st = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["data"]["status"]
        if st in ("completed", "failed"):
            return st
    return st


@pytest.mark.skipif(not _db_ready(), reason="数据库或规则库不可用")
def test_compare_review_flow():
    h = _admin_headers()
    old = _upload(h, "旧版.txt", "本理财产品保本保收益，零风险。")
    # 新版在首行基础上追加一行 → 块级 diff 产出 "added" 变更
    new = _upload(h, "新版.txt", "本理财产品保本保收益，零风险。\n预期年化收益率5.8%。")

    created = client.post(
        "/api/v1/tasks",
        headers=h,
        json={"document_id": new, "base_document_id": old, "task_name": "对比审查"},
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task_id"]

    st = _wait_completed(h, task_id)
    assert st == "completed"

    report = client.get(f"/api/v1/tasks/{task_id}/report", headers=h).json()["data"]
    assert report.get("diff_changes")
    assert any(c.get("change_type") == "added" for c in report["diff_changes"])

    md = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=h)
    assert "版本变更对照" in md.text
    assert "预期年化收益率5.8%" in md.text


@pytest.mark.skipif(not _db_ready(), reason="数据库或规则库不可用")
def test_normal_task_has_no_diff_changes():
    h = _admin_headers()
    doc_id = _upload(h, "普通.txt", "本理财产品保本保收益。")
    created = client.post(
        "/api/v1/tasks", headers=h, json={"document_id": doc_id, "task_name": "普通"}
    )
    task_id = created.json()["data"]["task_id"]
    st = _wait_completed(h, task_id)
    assert st == "completed"

    report = client.get(f"/api/v1/tasks/{task_id}/report", headers=h).json()["data"]
    assert not report.get("diff_changes")
    md = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=h).text
    assert "版本变更对照" not in md
