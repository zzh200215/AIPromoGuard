"""审核签发：schema 约束与鉴权回归（无需数据库，本地可跑）。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.main import app
from src.api.schemas.task import SignOffRequest

client = TestClient(app)


def test_sign_off_request_rejects_bad_decision_and_long_note():
    """decision 只允许 released/rejected；意见上限 500 字。"""
    with pytest.raises(ValidationError):
        SignOffRequest(decision="approved")
    with pytest.raises(ValidationError):
        SignOffRequest(decision="pending_confirm")
    req = SignOffRequest(decision="released", note="同意放行")
    assert req.note == "同意放行"
    with pytest.raises(ValidationError):
        SignOffRequest(decision="released", note="长" * 501)


def test_sign_off_endpoints_require_authentication():
    """签发是正式合规动作：匿名读写都必须 401。"""
    post_response = client.post("/api/v1/tasks/1/sign-off", json={"decision": "released"})
    assert post_response.status_code == 401
    assert post_response.json()["code"] == 1101

    get_response = client.get("/api/v1/tasks/1/sign-off")
    assert get_response.status_code == 401
    assert get_response.json()["code"] == 1101
