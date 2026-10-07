import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_task_create_rejects_path_traversal_document_id():
    """document_id 严格白名单：穿越片段在 schema 层即被拒（IDOR 回归）。"""
    from pydantic import ValidationError
    from src.api.schemas.task import TaskCreate

    for bad in [
        "../2/doc_12345678",
        "..",
        "doc_12345678/../../x",
        "doc_ABCDEFGH",  # 非 hex
        "doc_1234",  # 长度不足
        "../2/docx_secret",
    ]:
        with pytest.raises(ValidationError):
            TaskCreate(document_id=bad)
    # 合法 id 通过，base_document_id 同样受约束
    ok = TaskCreate(document_id="doc_abcdef01", base_document_id="doc_12345678")
    assert ok.document_id == "doc_abcdef01"
    with pytest.raises(ValidationError):
        TaskCreate(document_id="doc_abcdef01", base_document_id="../1/doc_12345678")


def test_health_reports_dependency_state():
    response = client.get("/api/v1/health")

    assert response.status_code in (200, 503)
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] in ("ok", "degraded")
    assert set(body["data"]["dependencies"]) == {"mysql", "redis"}


def test_upload_requires_authentication():
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("product.txt", "test content", "text/plain")},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_task_document_content_requires_authentication():
    """复核对照视图接口与任务接口同源鉴权：匿名访问必须 401。"""
    response = client.get("/api/v1/tasks/1/document-content")

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_retry_endpoints_require_authentication():
    """任务重试与批次重试失败任务均为写操作：匿名访问必须 401。"""
    for url in ("/api/v1/tasks/1/retry", "/api/v1/batches/1/retry-failed"):
        response = client.post(url)

        assert response.status_code == 401, url
        assert response.json()["code"] == 1101, url


def test_upload_rejects_anonymous_unsupported_file():
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_unknown_route_404():
    response = client.get("/api/v1/no-such-endpoint")
    assert response.status_code == 404


def test_text_document_requires_authentication():
    """粘贴文本建档：匿名 401。"""
    response = client.post("/api/v1/documents/text", json={"text": "保本保收益测试"})
    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_notifications_require_authentication():
    """站内通知：匿名 401（列表/已读/全部已读三个入口）。"""
    for method, path in [
        ("get", "/api/v1/notifications"),
        ("post", "/api/v1/notifications/1/read"),
        ("post", "/api/v1/notifications/read-all"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == 1101, path
