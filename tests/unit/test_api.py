from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


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
