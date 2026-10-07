"""AI Copilot 端点：入参校验与鉴权回归（无需数据库，本地可跑）。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.main import app
from src.api.schemas.ai import AskRequest

client = TestClient(app)


def test_ask_request_rejects_empty_and_oversized_question():
    """提问 1-500 字：防呆 + 防上下文滥用。"""
    with pytest.raises(ValidationError):
        AskRequest(question="")
    with pytest.raises(ValidationError):
        AskRequest(question="问" * 501)
    assert AskRequest(question="这篇材料的主要风险是什么").question.startswith("这")


def test_ask_requires_authentication():
    response = client.post(
        "/api/v1/ai/tasks/1/ask",
        json={"question": "主要风险是什么"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_rewrite_requires_authentication():
    response = client.post("/api/v1/ai/results/1/rewrite")

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_summary_requires_authentication():
    response = client.post("/api/v1/ai/tasks/1/summary")

    assert response.status_code == 401
    assert response.json()["code"] == 1101


def test_verdict_advice_requires_authentication():
    response = client.post("/api/v1/ai/results/1/verdict-advice")

    assert response.status_code == 401
    assert response.json()["code"] == 1101
