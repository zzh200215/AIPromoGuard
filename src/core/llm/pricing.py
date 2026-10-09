"""模型牌价与成本预估（成本归因）。

token 用量只有换算成金额才能回答"这次审查花了多少钱"。牌价表按厂商公开牌价
维护（单位：元 / 百万 tokens）；模型名按**精确名优先、家族子串兜底**匹配
（qwen3.7-flash 归 flash 档，qwen-plus-latest 归 plus 档）。牌价随官方调整会
变动，这里只做预估口径，精确计费以供应商控制台账单为准。
"""

# 精确模型名 → (输入 元/百万tokens, 输出 元/百万tokens)
# 当前接入：商汤日日新 Token Plan 网关（2026-10-09 起，公测免费——
# 每模型 5 小时 1500 次，定价全部为 0）。**正式计费后必须更新本表**，
# 否则这些模型会按 0 成本上报、低估支出。此表优先于下面的家族子串表
# （否则 deepseek-v4-flash / sensenova-6.8-flash-lite 会误命中 qwen 的 flash 档）。
_EXACT: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.0, 0.0),
    "deepseek-flash": (0.0, 0.0),
    "deepseek-v4.1-flash": (0.0, 0.0),
    "glm-5.2": (0.0, 0.0),
    "kimi-k3": (0.0, 0.0),
    "sensenova-6.8-flash-lite": (0.0, 0.0),
}

# 模型家族 → (输入 元/百万tokens, 输出 元/百万tokens)（阿里云百炼牌价）
_PRICING: dict[str, tuple[float, float]] = {
    "turbo": (0.3, 0.6),
    "flash": (0.15, 1.5),
    "plus": (0.8, 2.0),
    "max": (2.4, 9.6),
}

_UNKNOWN = (None, None)


def resolve_price(model: str | None) -> tuple[float, float] | tuple[None, None]:
    """解析模型牌价：精确名优先，家族子串兜底；未收录返回 (None, None)。"""
    name = (model or "").lower()
    if name in _EXACT:
        return _EXACT[name]
    for family, rates in _PRICING.items():
        if family in name:
            return rates
    return _UNKNOWN


def estimate_cost(usage: dict, model: str | None) -> dict:
    """由 token 用量预估成本（元）。未收录模型 priced=False，只统计 token。

    返回 {"estimated_cost_cny": float | None, "priced": bool}，不修改入参。
    记录缺失 prompt/completion 拆分时按输入价保守估算总量。
    """
    input_rate, output_rate = resolve_price(model)
    if input_rate is None:
        return {"estimated_cost_cny": None, "priced": False}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if prompt + completion == 0:
        prompt = int(usage.get("total_tokens") or 0)
    cost = prompt * input_rate / 1_000_000 + completion * output_rate / 1_000_000
    # 保留 6 位：小额调用（几十 token）在 4 位精度下会整成 0
    return {"estimated_cost_cny": round(cost, 6), "priced": True}
