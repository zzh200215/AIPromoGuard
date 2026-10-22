"""批量脚本运行级 LLM 成本账单。

在线审查链路的 token 用量走 state.llm_usage（成本归因）；离线批量脚本
（规则挖掘/对抗样本/消融/baseline/judge）此前不记账——额度事件正是发生
在这里。RecordingLLM 透明包装 QwenClient 逐次记录 usage，脚本结束调用
print_cost_summary() 报账"本次烧了多少 token、约多少钱"。
"""

import threading

from src.core.llm.pricing import estimate_cost

_LOCK = threading.Lock()
_LEDGER: dict = {}


def reset_ledger() -> None:
    with _LOCK:
        _LEDGER.clear()


def record_usage(usage: dict | None) -> None:
    """累加一次调用的用量；usage 缺 model 时补内层客户端模型名。"""
    if not usage:
        return
    with _LOCK:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            _LEDGER[key] = int(_LEDGER.get(key) or 0) + int(usage.get(key) or 0)
        _LEDGER["calls"] = int(_LEDGER.get("calls") or 0) + 1
        if not _LEDGER.get("model"):
            _LEDGER["model"] = usage.get("model")


def ledger_summary() -> dict:
    """返回本次运行累计用量 + 牌价预估；零调用返回空 dict。"""
    with _LOCK:
        data = dict(_LEDGER)
    if not data:
        return {}
    data.update(estimate_cost(data, data.get("model")))
    return data


def print_cost_summary(label: str = "本次运行") -> dict:
    """打印运行级成本账单；零调用也显式报零（确认没有意外烧钱）。"""
    data = ledger_summary()
    if not data:
        print(f"[{label}] LLM 成本账单：0 次调用 / 0 tokens（未产生 LLM 消耗）")
        return {}
    line = (
        f"[{label}] LLM 成本账单：{data['calls']} 次调用 / "
        f"{data['total_tokens']} tokens（prompt {data['prompt_tokens']} + "
        f"completion {data['completion_tokens']}）"
    )
    if data.get("model"):
        line += f"，模型 {data['model']}"
    if data.get("priced"):
        line += f"，预估 ¥{data['estimated_cost_cny']:.2f}（按牌价）"
    print(line)
    return data


class RecordingLLM:
    """QwenClient 透明包装：逐次记录 token 用量到运行级账本。

    complete/acomplete 记录单次 usage；achat_json 记录返回的累计 usage
    （内部多轮工具循环已合并）；chat 经 complete 记录。其余属性委托内层
    （model、json 能力等），用法与 QwenClient 完全一致。
    """

    def __init__(self, inner):
        self._inner = inner

    def complete(
        self,
        messages: list[dict],
        temperature: float | None = None,
        json_mode: bool = False,
        tools: list | None = None,
        tool_choice: str | dict | None = None,
    ):
        result = self._inner.complete(messages, temperature, json_mode, tools, tool_choice)
        record_usage({**result.usage, "model": result.model})
        return result

    async def acomplete(
        self,
        messages: list[dict],
        temperature: float | None = None,
        json_mode: bool = False,
        tools: list | None = None,
        tool_choice: str | dict | None = None,
    ):
        result = await self._inner.acomplete(
            messages, temperature, json_mode, tools, tool_choice
        )
        record_usage({**result.usage, "model": result.model})
        return result

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        return self.complete(messages, temperature).content

    async def achat_json(self, messages: list[dict], temperature: float | None = None, **kwargs):
        data, usage, tool_articles = await self._inner.achat_json(messages, temperature, **kwargs)
        record_usage({**(usage or {}), "model": getattr(self._inner, "model", None)})
        return data, usage, tool_articles

    def __getattr__(self, name):
        return getattr(self._inner, name)


def recording_llm(llm):
    """便捷入口：get_llm() 结果为 None 时原样返回，否则包一层 RecordingLLM。"""
    return RecordingLLM(llm) if llm is not None else None
