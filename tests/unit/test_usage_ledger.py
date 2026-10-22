"""运行级 LLM 成本账单（usage_ledger）测试：累加/牌价/包装器记账。"""

import pytest
from src.core.llm.usage_ledger import (
    RecordingLLM,
    ledger_summary,
    print_cost_summary,
    record_usage,
    recording_llm,
    reset_ledger,
)


@pytest.fixture(autouse=True)
def _clean_ledger():
    reset_ledger()
    yield
    reset_ledger()


# ---------- 账本累加 / 汇总 ----------


def test_record_usage_sums_and_counts_calls():
    record_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    record_usage({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30})
    summary = ledger_summary()
    assert summary["calls"] == 2
    assert summary["total_tokens"] == 45
    assert summary["prompt_tokens"] == 30


def test_record_usage_first_model_wins_and_estimate_attached():
    record_usage({"total_tokens": 10, "model": "qwen-plus"})
    record_usage({"total_tokens": 5, "model": "qwen-flash"})
    summary = ledger_summary()
    assert summary["model"] == "qwen-plus"
    assert summary["priced"] is True
    assert summary["estimated_cost_cny"] > 0


def test_record_usage_ignores_empty():
    record_usage(None)
    record_usage({})
    assert ledger_summary() == {}


def test_summary_empty_when_no_calls():
    assert ledger_summary() == {}


# ---------- print_cost_summary ----------


def test_print_zero_bill(capsys):
    data = print_cost_summary("冒烟")
    out = capsys.readouterr().out
    assert data == {}
    assert "0 次调用" in out and "冒烟" in out


def test_print_bill_with_cost(capsys):
    record_usage({"prompt_tokens": 1_000_000, "completion_tokens": 0, "model": "qwen-plus"})
    print_cost_summary("挖掘")
    out = capsys.readouterr().out
    assert "1 次调用" in out and "qwen-plus" in out and "预估 ¥0.80" in out


# ---------- RecordingLLM 包装 ----------


class _FakeResult:
    def __init__(self, content, usage, model):
        self.content = content
        self.usage = usage
        self.model = model
        self.total_tokens = usage.get("total_tokens", 0)


class _FakeInner:
    model = "qwen-plus"

    def complete(self, messages, temperature=None, json_mode=False, tools=None, tool_choice=None):
        return _FakeResult(
            "ok", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, self.model
        )

    async def achat_json(self, messages, temperature=None, **kwargs):
        return (
            [{"x": 1}],
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            [{"regulation_name": "测试法", "article_no": "第一条"}],
        )


def test_recording_llm_complete_and_chat_record():
    llm = RecordingLLM(_FakeInner())
    result = llm.complete([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    llm.chat([{"role": "user", "content": "hi"}])
    summary = ledger_summary()
    assert summary["calls"] == 2
    assert summary["total_tokens"] == 30  # 15 × 2
    assert summary["model"] == "qwen-plus"


def test_recording_llm_achat_json_records_merged_usage():
    import asyncio

    llm = RecordingLLM(_FakeInner())
    data, usage, tool_articles = asyncio.run(llm.achat_json([{"role": "user", "content": "hi"}]))
    assert data == [{"x": 1}]
    # 三元组透传：工具查证条款随结果返回（2026-10-19）
    assert tool_articles == [{"regulation_name": "测试法", "article_no": "第一条"}]
    summary = ledger_summary()
    assert summary["total_tokens"] == 150
    assert summary["calls"] == 1


def test_recording_llm_delegates_unknown_attrs():
    llm = RecordingLLM(_FakeInner())
    assert llm.model == "qwen-plus"


def test_recording_llm_none_passthrough():
    assert recording_llm(None) is None
    assert recording_llm(_FakeInner()) is not None
