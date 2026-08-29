"""baseline 对比实验：裸 LLM 直查 vs 全系统（规则+检索+LLM）在同一样本集上的差距。

回答"这套双引擎+检索架构到底带来多少提升"——简历/汇报主打数字的复现出口。
三列对照：
- rule     仅规则引擎（零 LLM 成本，变体集刻意绕开触发词 → 预期召回崩溃）
- naive    裸 LLM 直查（不做法规检索、不给规则库、单条 prompt 出结论）
- full     真实 LangGraph workflow（领域分类 + 混合检索/图谱召回 + 规则∥LLM + 融合）

指标口径与 evaluate.py 一致：标注点召回率 + 检出误报率（互为子串命中，
negative_ground_truth 命中直接计误报）。naive 跑 --runs 次取均值（LLM 非确定性）。

需要 DASHSCOPE_API_KEY 与本地 MySQL/向量库。observe-only，不进 CI 门禁。

用法（仓库根目录）:
    python scripts/evaluate/baseline_compare.py --runs 2
    python scripts/evaluate/baseline_compare.py --cases scripts/evaluate/variant_cases.json \
        --runs 3 --out baseline_report.json --limit 10
"""

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)

from src.core.llm.client import get_llm, merge_usage  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_EVALUATE_PATH = Path(__file__).resolve().parent / "evaluate.py"

_NAIVE_SYSTEM = (
    "你是资深金融合规审查员。请审查给定的金融产品营销文案，找出其中所有违反"
    "监管规定的表述（如刚性兑付、保本保收益、虚假宣传、误导销售、风险揭示缺失等）。"
)

_NAIVE_USER_TMPL = (
    "营销文案：\n{text}\n\n"
    "要求：\n"
    '1. 只输出 JSON：{{"violations": [{{"text": "原文违规表述（必须逐字摘抄原文，'
    '不要改写或概括）", "reason": "违规原因一句话"}}]}}\n'
    "2. 文案合规（正常风险披露不属违规）时输出空数组\n"
    "3. 不要输出 JSON 以外的任何内容"
)


def _load_evaluate():
    """复用 evaluate.py 的真实扫描管线（rule / full 引擎），不改动该文件。"""
    spec = importlib.util.spec_from_file_location("evaluate_for_baseline", _EVALUATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_violations(content: str) -> list[dict]:
    """宽容提取 naive 输出的 violations 数组（剥围栏/杂质，坏项跳过）。"""
    import re

    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("violations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [v for v in items if isinstance(v, dict) and str(v.get("text") or "").strip()]


def naive_scan(llm, case: dict) -> tuple[list[dict], dict | None]:
    """裸 LLM 直查：单条 prompt，无检索无规则库。返回 (findings, usage)。"""
    messages = [
        {"role": "system", "content": _NAIVE_SYSTEM},
        {"role": "user", "content": _NAIVE_USER_TMPL.format(text=case["text"][:1500])},
    ]
    usage = None
    for attempt in range(2):
        try:
            result = llm.complete(messages)
        except Exception:
            logger.exception("naive LLM 调用失败（case=%s）", case.get("id"))
            return [], usage
        usage = merge_usage(usage, result.usage)
        items = _parse_violations(result.content)
        if items or attempt == 1:
            return [
                {"source": "naive", "original_text": str(v["text"]).strip(), "confidence": None}
                for v in items
            ], usage
        messages = messages + [
            {"role": "assistant", "content": result.content},
            {"role": "user", "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象。"},
        ]
    return [], usage


def score_findings(findings: list[dict], case: dict) -> dict:
    """与 evaluate.py 同口径的 span 计分：召回率 / 误报数 / 检出数。"""
    gt = case.get("ground_truth", [])
    negatives = case.get("negative_ground_truth") or []

    def _overlaps(a: str, b: str) -> bool:
        return bool(a) and bool(b) and (a in b or b in a)

    matched_gt = set()
    fp = 0
    for f in findings:
        text = f.get("original_text") or ""
        if any(_overlaps(text, n.get("text", "")) for n in negatives):
            fp += 1
            continue
        matched = [g for g in gt if _overlaps(text, g.get("text", ""))]
        if matched:
            matched_gt.update(id(g) for g in matched)
        else:
            fp += 1
    recall = len(matched_gt) / len(gt) if gt else 1.0
    precision = (len(findings) - fp) / len(findings) if findings else 1.0
    return {
        "gt_count": len(gt),
        "found_count": len(findings),
        "tp_gt": len(matched_gt),
        "fp": fp,
        "recall": recall,
        "fpr": 1 - precision,
    }


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().parent / "variant_cases.json"),
        help="样本集 JSON（默认 held-out 变体集）",
    )
    parser.add_argument("--runs", type=int, default=2, help="naive 重复次数（LLM 非确定性）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个案例（冒烟用）")
    parser.add_argument("--out", default=None, help="明细 JSON 输出路径")
    parser.add_argument(
        "--skip-full", action="store_true", help="跳过 full 引擎（只跑 rule+naive）"
    )
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        print("未配置 DASHSCOPE_API_KEY，无法跑 naive/full 对比（exit 2）")
        return 2
    llm = get_llm()
    if llm is None:
        print("LLM 客户端初始化失败（exit 2）")
        return 2

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = data["cases"][: args.limit] if args.limit else data["cases"]
    ev = _load_evaluate()
    print(
        f"baseline 对比 | 样本 {len(cases)} 案例（标注点 "
        f"{sum(len(c.get('ground_truth') or []) for c in cases)}） | naive ×{args.runs}"
    )
    print("=" * 72)

    arms: dict[str, list[dict]] = {
        "rule": [],
        **{f"naive#{i}": [] for i in range(1, args.runs + 1)},
    }
    if not args.skip_full:
        arms["full"] = []
    naive_usage = None

    for idx, case in enumerate(cases, start=1):
        # 1) 规则引擎（零成本基线）
        arms["rule"].append(score_findings(ev._scan_rule_engine(case), case))
        # 2) 裸 LLM × runs
        for i in range(1, args.runs + 1):
            findings, usage = naive_scan(llm, case)
            naive_usage = merge_usage(naive_usage, usage)
            arms[f"naive#{i}"].append(score_findings(findings, case))
        # 3) 全系统
        if not args.skip_full:
            arms["full"].append(score_findings(ev._scan_full(case), case))
        print(f"[{idx}/{len(cases)}] {case['id']} 完成")

    def _aggregate(results: list[dict]) -> dict:
        gt = sum(r["gt_count"] for r in results)
        tp = sum(r["tp_gt"] for r in results)
        found = sum(r["found_count"] for r in results)
        fp = sum(r["fp"] for r in results)
        return {
            "recall": round(tp / gt, 4) if gt else 1.0,
            "fpr": round(fp / found, 4) if found else 0.0,
            "found": found,
            "fp": fp,
            "tp_gt": tp,
            "gt": gt,
        }

    print(f"\n{'引擎':<12}{'召回率':>10}{'误报率':>10}{'检出':>8}{'误报数':>8}{'命中标注':>10}")
    print("-" * 72)
    summary = {}
    for name, results in arms.items():
        agg = _aggregate(results)
        summary[name] = agg
        print(
            f"{name:<12}{_fmt_pct(agg['recall']):>10}{_fmt_pct(agg['fpr']):>10}"
            f"{agg['found']:>8}{agg['fp']:>8}{agg['tp_gt']:>10}"
        )

    naive_runs = [v for k, v in summary.items() if k.startswith("naive#")]
    if len(naive_runs) > 1:
        mean_recall = sum(r["recall"] for r in naive_runs) / len(naive_runs)
        mean_fpr = sum(r["fpr"] for r in naive_runs) / len(naive_runs)
        spread = max(r["recall"] for r in naive_runs) - min(r["recall"] for r in naive_runs)
        summary["naive_mean"] = {
            "recall": round(mean_recall, 4),
            "fpr": round(mean_fpr, 4),
            "recall_spread": round(spread, 4),
        }
        print(
            f"\nnaive {len(naive_runs)} 次均值：召回 {_fmt_pct(mean_recall)}"
            f"（极差 {_fmt_pct(spread)}）| 误报率 {_fmt_pct(mean_fpr)}"
        )
    print(f"naive token 用量：{naive_usage}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "cases_file": str(args.cases),
                    "case_count": len(cases),
                    "naive_runs": args.runs,
                    "summary": summary,
                    "usage_naive": naive_usage,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n明细已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
