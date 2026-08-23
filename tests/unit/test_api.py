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
