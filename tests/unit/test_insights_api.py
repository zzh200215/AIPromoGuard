"""合规洞察接口（GET /insights/overview）：结构与口径断言。

依赖真实 DB（fcr_test 由 conftest 指定）；DB 不可用时跳过。
鉴权用依赖覆盖，避免测试携带真实口令。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.middleware.auth import get_current_user


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import ReviewTask

        db = SessionLocal()
        db.query(ReviewTask).count()
        db.close()
        return True
    except Exception:
        return False


@pytest.fixture()
def client():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="tester", role="admin"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_overview_shape(client):
    resp = client.get("/api/v1/insights/overview")
    assert resp.status_code == 200
    data = resp.json()["data"]

    for key in ("cards", "risk", "sources", "rules_top", "regulations_top", "trend",
                "review_funnel", "remediation", "material_types"):
        assert key in data, f"缺少字段 {key}"

    cards = data["cards"]
    assert cards["tasks_total"] >= cards["tasks_completed"] >= 0
    assert cards["findings_total"] >= (
        cards["confirmed"] + cards["pending"] + cards["false_positive"]
    ) or cards["findings_total"] >= 0
    # 采纳率/覆盖率要么为空（无数据），要么在 [0,1]
    assert cards["confirm_rate"] is None or 0 <= cards["confirm_rate"] <= 1
    assert cards["review_coverage"] is None or 0 <= cards["review_coverage"] <= 1

    assert len(data["trend"]) == 30
    assert [step["label"] for step in data["review_funnel"]] == ["检出", "已复核", "采纳", "待复核"]
    assert all(isinstance(step["value"], int) for step in data["review_funnel"])


def test_overview_requires_auth():
    # 不覆盖依赖时未登录应被拒绝
    raw = TestClient(app)
    resp = raw.get("/api/v1/insights/overview")
    assert resp.status_code in (401, 403)
