"""bench 脚本共享工具：百分位统计（小样本避免插值口径分歧）。"""


def _pct(sorted_values: list[float], p: float) -> float:
    """最近秩百分位（输入需已排序）。"""
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, round(p / 100 * len(sorted_values) + 0.5) - 1))
    return sorted_values[idx]


def pct_stats(values: list[float]) -> dict:
    """毫秒样本 → {n, p50_ms, p95_ms, mean_ms, max_ms}。"""
    sv = sorted(values)
    if not sv:
        return {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0, "max_ms": 0.0}
    return {
        "n": len(sv),
        "p50_ms": round(_pct(sv, 50), 1),
        "p95_ms": round(_pct(sv, 95), 1),
        "mean_ms": round(sum(sv) / len(sv), 1),
        "max_ms": round(sv[-1], 1),
    }
