"""llm_scan 单块基准：测延迟与输出长度的真实分布（不是单次快照）。

为什么需要它（2026-10-22 实测教训）：
- 同一份材料、同一配置，两次真实审查耗时 277s / 302s / 411s；
- 同一块、同一提示词，两次调用 8.1s 与 21.0s（完成 token 515 vs 1844）；
- 只用"跑一次比一次"来判断提速方案，等于拿噪声当结论——本工具强制多次取中位数/p90。

用法：
    # 基线：某材料的第 1 块，重复 5 次
    python scripts/bench/bench_llm_scan.py --material data/uploads/demo/verify_dedup_1022.txt \
        --block 1 --reps 5

    # 对比"输出精简"变体（同块同次数）
    python scripts/bench/bench_llm_scan.py --block 1 --reps 5 --variant brevity

输出：每次的耗时/tokens/findings + 中位数与 p90 汇总。
"""

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from src.core.agents.nodes.regulation_match import regulation_match  # noqa: E402
from src.core.llm.client import get_llm  # noqa: E402
from src.core.llm.prompts.review import build_review_messages  # noqa: E402
from src.parsers import parse_document  # noqa: E402

VARIANTS = {
    "baseline": "",
    "brevity": (
        "8) 每条独立违规必须单独输出：同一句里的不同违规点要拆成多条，不得合并；"
        "但每条 reason 不超过 60 字、suggestion 不超过 40 字，不复述原文、不展开推理。"
    ),
}


def _blocks(path: str) -> list[str]:
    doc = parse_document(path)
    return [b.text for b in doc.blocks if (b.text or "").strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="llm_scan 单块基准（多次取中位数）")
    ap.add_argument("--material", default="data/uploads/demo/verify_dedup_1022.txt")
    ap.add_argument("--block", type=int, default=1, help="第几块（1 起）")
    ap.add_argument("--reps", type=int, default=3, help="重复次数，至少 3 才有统计意义")
    ap.add_argument("--json", default="", help="把结果写成 JSON（做矩阵对照时用）")
    ap.add_argument("--variant", choices=list(VARIANTS), default="baseline")
    ap.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="工具循环轮数（0=用配置值）。生产 max_tool_rounds=2，可测降到 1 的收益",
    )
    ap.add_argument(
        "--tools", choices=["on", "off"], default="on",
        help="是否启用 function calling 工具循环（生产默认 on）",
    )
    args = ap.parse_args()

    blocks = _blocks(args.material)
    if not blocks:
        print("材料里没有可用文本块")
        return
    idx = min(max(args.block, 1), len(blocks)) - 1
    text = blocks[idx]

    if args.rounds > 0:
        from src.utils.config import settings as _s

        _orig_cfg = type(_s).app_config

        def _patched(self, section):
            cfg = _orig_cfg(self, section)
            if section == "llm":
                tc = {**(cfg.get("tool_calling") or {}), "max_tool_rounds": args.rounds}
                cfg = {**cfg, "tool_calling": tc}
            return cfg

        type(_s).app_config = _patched

    articles = regulation_match({"text": "".join(blocks), "domain": None}).get(
        "matched_articles", []
    )
    llm = get_llm()
    if llm is None:
        print("未配置 LLM key，无法基准")
        return

    print(f"材料 {args.material} | 共 {len(blocks)} 块 | 取第 {idx + 1} 块 | "
          f"召回条款 {len(articles)} | 变体 {args.variant} | tools {args.tools} | 重复 {args.reps}")

    rows = []
    for i in range(args.reps):
        msgs = build_review_messages(text, articles)
        if VARIANTS[args.variant]:
            msgs[0]["content"] = msgs[0]["content"] + VARIANTS[args.variant]
        t0 = time.time()
        try:
            data, usage, _ = asyncio.run(
                llm.achat_json(msgs, temperature=0.1, enable_tool_calls=args.tools == "on")
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  第 {i + 1} 次失败: {type(exc).__name__} {str(exc)[:80]}")
            continue
        rows.append(
            {
                "s": round(time.time() - t0, 1),
                "p": usage.get("prompt_tokens") or 0,
                "c": usage.get("completion_tokens") or 0,
                "n": len(data),
            }
        )
        print(f"  第 {i + 1} 次: {rows[-1]['s']}s | prompt {rows[-1]['p']} | "
              f"completion {rows[-1]['c']} | findings {rows[-1]['n']}", flush=True)

    if len(rows) < 2:
        print("有效样本不足，无法统计")
        return

    secs = [r["s"] for r in rows]
    comps = [r["c"] for r in rows]
    print("\n汇总（重复 %d 次）:" % len(rows))
    p90 = sorted(secs)[max(int(len(secs) * 0.9) - 1, 0)]
    print(f"  耗时   中位数 {statistics.median(secs)}s | p90 {p90}s | "
          f"区间 {min(secs)}-{max(secs)}s | 波动 {max(secs) / max(min(secs), 0.1):.1f}×")
    print(f"  输出   中位数 {int(statistics.median(comps))} tokens | "
          f"区间 {min(comps)}-{max(comps)}")
    print(f"  检出   合计 {sum(r['n'] for r in rows)} 条 / {len(rows)} 次")

    if args.json:
        import json as _json
        from pathlib import Path as _Path

        payload = {
            "material": args.material, "block": idx + 1, "variant": args.variant,
            "tools": args.tools, "rounds": args.rounds, "reps": len(rows),
            "median_s": statistics.median(secs), "p90_s": p90,
            "min_s": min(secs), "max_s": max(secs),
            "median_completion": int(statistics.median(comps)),
            "findings_total": sum(r["n"] for r in rows), "rows": rows,
        }
        out = _Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  JSON → {out}")


if __name__ == "__main__":
    main()
