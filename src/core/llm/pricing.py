"""模型牌价与成本预估（成本归因）。

token 用量只有换算成金额才能回答"这次审查花了多少钱"。牌价表按阿里云百炼
公开牌价维护（单位：元 / 百万 tokens）；模型名按家族子串匹配（qwen3.7-flash
归 flash 档，qwen-plus-latest 归 plus 档）。牌价随官方调整会变动，这里只做
预估口径，精确计费以百炼控制台账单为准。
"""

# 模型家族 → (输入 元/百万tokens, 输出 元/百万tokens)
_PRICING: dict[str, tuple[float, float]] = {
    "turbo": (0.3, 0.6),
    "flash": (0.15, 1.5),
    "plus": (0.8, 2.0),
    "max": (2.4, 9.6),
}

_UNKNOWN = (None, None)


def resolve_price(model: str | None) -> tuple[float, float] | tuple[None, None]:
    """按家族子串解析牌价；未收录的模型返回 (None, None)。"""
    name = (model or "").lower()
    for family, rates in _PRICING.items():
        if family in name:
            return rates
    return _UNKNOWN


def estimate_cost(usage: dict, model: str | None) -> dict:
    """由 token 用量预估成本（元）。未收录模型 priced=False，只统计 token。

    返回 {"estimated_cost_cny": float | None, "priced": bool}，就地并报告告不修改入参。
    """
    input_rate, output_rate = resolve_price(model)
    if input_rate is None:
        return {"estimated_cost_cny": None, "priced": False}
    cost = (
        int(usage.get("prompt_tokens") or 0) * input_rate / 1_000_000
        + int(usage.get("completion_tokens") or 0) * output_rate / 1_000_000
    )
    return {"estimated_cost_cny": round(cost, 4), "priced": True}
