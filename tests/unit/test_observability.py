"""Langfuse 可观测性埋点单元测试：未配置 no-op + 注入 fake 验证记录行为。"""

from unittest.mock import MagicMock

from src.core.llm.observability import LLMObserver


def test_disabled_when_unconfigured(monkeypatch):
    """未配置 Key：enabled 为 False，所有记录方法 no-op 不抛错。"""
    from src.utils.config import settings

    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    observer = LLMObserver()
    assert observer.enabled is False
    # 记录方法必须异常安全
    observer.record_generation(
        name="chat:test", model="m", input=[], output="o",
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )
    observer.record_node("classify", cost_ms=12, task_id=1)


def test_record_generation_with_fake_client():
    """注入 fake client（模拟已启用）：generation 记录带 model/usage/output。"""
    fake = MagicMock()
    observer = LLMObserver(client=fake)
    assert observer.enabled is True

    observer.record_generation(
        name="chat:qwen-plus:json",
        model="qwen-plus",
        input=[{"role": "user", "content": "q"}],
        output='{"findings": []}',
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        metadata={"task_id": 7},
    )
    fake.start_span.assert_called_once()
    kwargs = fake.start_span.call_args.kwargs
    assert kwargs["name"] == "chat:qwen-plus:json"
    assert kwargs["metadata"]["model"] == "qwen-plus"
    span = fake.start_span.return_value
    span.update.assert_called_once_with(
        model="qwen-plus",
        usage={"input": 10, "output": 5, "total": 15, "unit": "TOKENS"},
    )
    span.end.assert_called_once_with(output='{"findings": []}')


def test_record_node_with_fake_client():
    fake = MagicMock()
    observer = LLMObserver(client=fake)
    observer.record_node("rule_scan", cost_ms=250, status="completed", task_id=42)
    kwargs = fake.start_span.call_args.kwargs
    assert kwargs["name"] == "node:rule_scan"
    assert kwargs["metadata"]["cost_ms"] == 250
    assert kwargs["metadata"]["task_id"] == 42
    fake.start_span.return_value.end.assert_called_once()


def test_span_exceptions_are_swallowed():
    """埋点底层抛错不能影响业务主流程。"""
    fake = MagicMock()
    fake.start_span.side_effect = RuntimeError("langfuse down")
    observer = LLMObserver(client=fake)
    observer.record_generation(
        name="chat:m", model="m", input=[], output="o", usage={}
    )  # 不抛错
    observer.record_node("report", cost_ms=1)
