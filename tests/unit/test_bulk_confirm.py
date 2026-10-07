"""批量判定接口：schema 约束与鉴权回归（无需数据库，本地可跑）。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.main import app
from src.api.routers.results import BulkConfirmRequest

client = TestClient(app)


def test_bulk_confirm_request_rejects_empty_and_oversized_batch():
    """result_ids 非空且上限 200：防呆 + 防批量滥用。"""
    with pytest.raises(ValidationError):
        BulkConfirmRequest(result_ids=[], verdict="confirmed")
    with pytest.raises(ValidationError):
        BulkConfirmRequest(result_ids=list(range(1, 202)), verdict="confirmed")
    with pytest.raises(ValidationError):
        # verdict 只允许 confirmed / false_positive，pending_confirm 不是有效目标态
        BulkConfirmRequest(result_ids=[1, 2], verdict="pending_confirm")


def test_bulk_confirm_dedup_and_shape():
    """重复 id 由服务端去重处理，schema 层接受任意非空列表。"""
    req = BulkConfirmRequest(result_ids=[3, 3, 5], verdict="false_positive", note="误报")
    assert req.result_ids == [3, 3, 5]


def test_bulk_confirm_requires_authentication():
    response = client.post(
        "/api/v1/results/bulk-confirm",
        json={"result_ids": [1, 2], "verdict": "confirmed"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_tasks_search_param_requires_authentication():
    """列表搜索为写路径之外的普通读取，但同样必须先登录。"""
    response = client.get("/api/v1/tasks", params={"search": "稳健"})

    assert response.status_code == 401
    assert response.json()["code"] == 1101
