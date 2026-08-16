"""LLM 客户端单元测试：结构化输出解析、纠错重试、模型降级链、usage 采集。

异步方法用 asyncio.run 在同步测试中驱动（项目未配置异步 pytest 插件，
保持测试零额外依赖）。
"""

import asyncio
from types import SimpleNamespace

from src.core.llm.client import (
    CompletionResult,
    QwenClient,
    extract_findings,
    merge_usage,
)


# ---- extract_findings：三种输出形态兼容 ----


def test_extract_findings_bare_list():
    assert extract_findings('[{"issue": "a"}]') == [{"issue": "a"}]


def test_extract_findings_wrapper_object():
    assert extract_findings('{"findings": [{"issue": "a"}]}') == [{"issue": "a"}]
    assert extract_findings('{"violations": [{"issue": "a"}]}') == [{"issue": "a"}]


def test_extract_findings_fenced():
    assert extract_findings('```json\n[{"issue": "a"}]\n```') == [{"issue": "a"}]


def test_extract_findings_invalid_returns_none():
    assert extract_findings("不是 JSON") is None
    assert extract_findings('{"no_expected_key": 1}') is None
    assert extract_findings("") is None


def test_extract_findings_empty_list_ok():
    assert extract_findings("[]") == []
    assert extract_findings('{"findings": []}') == []


# ---- merge_usage ----


def test_merge_usage_accumulates_and_counts_calls():
    merged = merge_usage(
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        None,
    )
    assert merged == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "calls": 2,
    }


def test_merge_usage_empty():
    assert merge_usage() == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "calls": 0,
    }


# ---- 客户端行为（跳过 __init__，注入假 OpenAI 客户端） ----


def _resp(content: str, usage: dict | None = None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=(usage or {}).get("prompt_tokens", 0),
            completion_tokens=(usage or {}).get("completion_tokens", 0),
            total_tokens=(usage or {}).get("total_tokens", 0),
        ),
    )


class _FakeAsyncOpenAI:
    """按脚本回放的假 AsyncOpenAI：记录 create 参数，支持按模型抛错。"""

    def __init__(self, script: list, fail_models: set[str] | None = None):
        self.script = list(script)
        self.calls: list[dict] = []
        self._fail_models = fail_models or set()

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] in self._fail_models:
            raise RuntimeError(f"model {kwargs['model']} unavailable")
        return self.script.pop(0)


class _NoJsonModeFirst(_FakeAsyncOpenAI):
    """首次带 response_format 的请求报不支持，模拟旧网关/模型。"""

    def __init__(self, script):
        super().__init__(script)
        self.call_count = 0

    async def create(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1 and "response_format" in kwargs:
            raise RuntimeError("response_format is not supported for this model")
        return await super().create(**kwargs)


def _bare_client(fake_async, model: str | None = None):
    """构造绕过 __init__ 的 QwenClient（不依赖真实 API Key/网络）。"""
    from src.core.llm.observability import LLMObserver

    client = QwenClient.__new__(QwenClient)
    client._client = None
    client._aclient = fake_async
    client._aclient_loop = object()  # 哨兵，防止 _async_client 重建真实客户端
    client._async_client = lambda: fake_async  # 实例属性遮蔽，固定返回假客户端
    client.model = model or "test-model"
    client._observer = LLMObserver()  # 未配置 → no-op
    return client


def test_achat_json_parses_wrapper_and_collects_usage():
    fake = _FakeAsyncOpenAI(
        [_resp('{"findings": [{"issue": "a"}]}', {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})]
    )
    client = _bare_client(fake)
    data, usage = asyncio.run(client.achat_json([{"role": "user", "content": "q"}]))
    assert data == [{"issue": "a"}]
    assert usage["total_tokens"] == 15
    # 结构化输出模式：请求带 response_format
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_achat_json_repairs_invalid_json():
    """首次输出非法 JSON 时带错误反馈重试一次（自纠错），usage 累计两次调用。"""
    fake = _FakeAsyncOpenAI([
        _resp("我觉得这段话有违规", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
        _resp('{"findings": []}', {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}),
    ])
    client = _bare_client(fake)
    data, usage = asyncio.run(client.achat_json([{"role": "user", "content": "q"}]))
    assert data == []
    assert usage["calls"] == 2
    assert usage["total_tokens"] == 25
    # 第二次调用的消息里包含纠错指令与原错误输出
    repair_messages = fake.calls[1]["messages"]
    assert any("不是合法的 JSON" in m.get("content", "") for m in repair_messages)
    assert repair_messages[-2]["role"] == "assistant"


def test_achat_json_repair_still_fails_returns_empty():
    fake = _FakeAsyncOpenAI([
        _resp("bad"),
        _resp("still bad"),
    ])
    client = _bare_client(fake)
    data, usage = asyncio.run(client.achat_json([{"role": "user", "content": "q"}]))
    assert data == []


def test_acomplete_falls_back_to_next_model():
    """主模型失败按 fallback_models 降级，返回实际使用的模型与 usage。"""
    fake = _FakeAsyncOpenAI(
        [_resp("ok", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})],
        fail_models={"test-model"},
    )
    client = _bare_client(fake, model="test-model")
    # settings.app_config("llm") 来自真实 configs/app.yaml，fallback_models=[qwen-turbo]
    result = asyncio.run(client.acomplete([{"role": "user", "content": "q"}]))
    assert result.model == "qwen-turbo"
    assert result.content == "ok"
    assert result.total_tokens == 2


def test_acomplete_json_mode_unsupported_falls_back_without_param():
    """模型不支持 response_format 时去掉该参数重试（同模型）。"""
    fake = _NoJsonModeFirst([_resp('{"findings": []}')])
    client = _bare_client(fake)
    result = asyncio.run(client.acomplete([{"role": "user", "content": "q"}], json_mode=True))
    assert result.content == '{"findings": []}'
    assert fake.call_count == 2
    # 第一次带 response_format 的请求在 super 记录前抛错，calls 里只有成功的那次（无该参数）
    assert "response_format" not in fake.calls[0]


def test_completion_result_total_tokens():
    result = CompletionResult(
        content="x", model="m", usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    )
    assert result.total_tokens == 7
    assert CompletionResult(content="x", model="m", usage={}).total_tokens == 0


def test_async_client_rebuilt_when_event_loop_changes(monkeypatch):
    """回归：llm_scan 每次审查走一次 asyncio.run()（新事件循环），httpx 连接池
    绑死旧 loop 会报 "Event loop is closed"——loop 更替时必须重建 AsyncOpenAI。
    """
    from src.utils.config import settings

    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test-only")
    client = QwenClient.__new__(QwenClient)
    client._aclient = "stale"
    client._aclient_loop = object()

    async def _get():
        return client._async_client()

    c1 = asyncio.run(_get())
    assert c1 != "stale"  # 旧客户端被替换
    c2 = asyncio.run(_get())
    assert c2 is not c1  # 新 loop → 再次重建，不复用旧池
    assert client._aclient_loop is not None
