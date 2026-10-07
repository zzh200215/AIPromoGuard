"""撤销判定接口：schema 约束与鉴权回归（无需数据库，本地可跑）。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.main import app
from src.api.routers.results import RevertRequest

client = TestClient(app)


def test_revert_request_rejects_empty_and_oversized_batch():
    """result_ids 非空且上限 200，与 bulk-confirm 同口径。"""
    with pytest.raises(ValidationError):
        RevertRequest(result_ids=[])
    with pytest.raises(ValidationError):
        RevertRequest(result_ids=list(range(1, 202)))


def test_revert_request_note_optional():
    """备注可省略；省略时不追加撤销说明。"""
    req = RevertRequest(result_ids=[3, 3, 5])
    assert req.note is None
    assert req.result_ids == [3, 3, 5]


def test_revert_requires_authentication():
    """撤销是写路径，未登录一律 401。"""
    response = client.post("/api/v1/results/revert", json={"result_ids": [1, 2]})

    assert response.status_code == 401
    assert response.json()["code"] == 1101
