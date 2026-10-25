"""Copilot 工具化（P3）机制级测试：受限循环 / 引用校验 / 降级路径。"""

from types import SimpleNamespace

import src.services.review_copilot as rc


class _ScriptedLLM:
    """按脚本回放：先发 tool_calls，再出最终回答（或按预设耗尽预算）。"""

    def __init__(self, rounds):
        # rounds: 每轮一个 SimpleNamespace(content, usage, tool_calls)
        self.rounds = list(rounds)
        self.calls: list[list[dict]] = []

    def complete(self, messages, temperature=None, tools=None, tool_choice=None):
        self.calls.append(messages)
        if self.rounds:
            return self.rounds.pop(0)
        return SimpleNamespace(content="（兜底）", usage=None, tool_calls=None)


def _task():
    return SimpleNamespace(id=1, document_name="d.txt", domain="fund", status="completed")


def test_tool_loop_reaches_final_answer_and_counts():
    """脚本：一轮工具调用 → 最终回答。循环计数与消息结构正确。"""
    llm = _ScriptedLLM([
        SimpleNamespace(
            content=None,
            usage={"total_tokens": 10},
            tool_calls=[
                {"id": "t1", "name": "search_regulations", "arguments": '{"query":"保本"}'}
            ],
        ),
        SimpleNamespace(
            content='{"answer":"依据条款…","refs":[]}',
            usage={"total_tokens": 20},
            tool_calls=None,
        ),
    ])
    content, usage, used = rc._copilot_agent_answer(
        llm, None, _task(), "保本承诺怎么看？", [], "ctx", set()
    )
    assert used == 1
    assert usage["total_tokens"] == 30
    assert "answer" in content
    # 第二轮消息包含 assistant tool_calls + tool 结果对
    second = llm.calls[1]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "t1"


def test_tool_loop_budget_falls_back_plain():
    """连续 tool_calls 耗尽预算：回退一次无工具补全，保证有回答。"""
    def tool_round(n):
        return SimpleNamespace(
            content=None, usage=None,
            tool_calls=[{"id": f"t{n}", "name": "get_task_results", "arguments": "{}"}],
        )

    llm = _ScriptedLLM(
        [tool_round(i) for i in range(rc._COPILOT_TOOL_ROUNDS + 1)]
        + [SimpleNamespace(content='（兜底）', usage=None, tool_calls=None)]
    )
    content, usage, used = rc._copilot_agent_answer(llm, None, _task(), "q", [], "ctx", set())
    assert used == rc._COPILOT_TOOL_ROUNDS + 1  # 回合上限先于调用上限触发（单调用/轮）
    assert content == "（兜底）"  # 预算耗尽后的无工具补全产出
    # 兜底调用的消息不含 tool 角色（原始三段消息）
    last = llm.calls[-1]
    assert all(m.get("role") != "tool" for m in last)


def test_search_regulations_collects_valid_ids():
    """法规检索工具的命中进引用校验池（防模型张冠李戴的口径不变）。"""
    schemas, execute, valid_ids = rc._copilot_tools(None, _task())
    assert {s["function"]["name"] for s in schemas} == {
        "search_regulations", "get_task_results", "get_result_trail", "search_penalty_cases",
    }
    assert len(valid_ids) == 0  # 初始为空，命中由 execute 收集


def test_get_result_trail_scoped_to_task():
    """证据链工具按任务隔离：他任务/不存在的 result_id 拒绝。"""
    schemas, execute, _ = rc._copilot_tools(_FakeDb(), _task())
    out = execute("get_result_trail", '{"result_id": 999}')
    assert "error" in out


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None


class _FakeDb:
    def query(self, *a, **k):
        return _FakeQuery()
