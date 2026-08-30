"""消融实验：逐组件关闭跑全链路，量化规则路 / 图谱路 / LLM 语义路的贡献。

回答"多 Agent 协作里每个组件各带来多少"——组件贡献表的复现出口。
对照臂（同一变体集、同一 span 口径，复用 evaluate.py 真实管线与
baseline_compare.score_findings 计分）：

- full      完整链路：规则引擎 + 混合检索/图谱召回 + LLM 语义审查
- no_graph  关图谱第三路（regulation_match 的 graph_recall 开关置 False）
- no_rule   关规则引擎（rule_scanner 打点为空扫描，LLM+图谱路独立作战）
- no_llm    关 LLM（get_llm 返回 None，llm_scan 按既有降级链路空跑），
            等价于纯规则口径，用于校验与 baseline 规则臂一致

关闭方式为运行时 monkeypatch 节点模块的依赖入口，不改任何业务代码与配置；
需要 DASHSCOPE_API_KEY 与本地 MySQL/向量库。observe-only，不进 CI 门禁。

用法（仓库根目录）:
    python scripts/evaluate/ablation.py --out data/eval/ablation.json
    python scripts/evaluate/ablation.py --limit 10        # 冒烟
"""

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)

from src.core.llm.usage_ledger import print_cost_summary, recording_llm  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_EVALUATE_PATH = Path(__file__).resolve().parent / "evaluate.py"
_BASELINE_PATH = Path(__file__).resolve().parent / "baseline_compare.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Ablation:
    """运行时组件开关：patch 各节点模块的依赖入口，恢复时还原。"""

    def __init__(self):
        self._saved: list[tuple] = []

    def _patch(self, module, attr, value):
        self._saved.append((module, attr, getattr(module, attr)))
        setattr(module, attr, value)

    def restore(self):
        for module, attr, value in reversed(self._saved):
            setattr(module, attr, value)
        self._saved.clear()

    def disable_graph(self):
        from src.core.agents.nodes import regulation_match

        base = settings.app_config("workflow")

        def cfg(key):
            data = dict(base) if key == "workflow" else settings.app_config(key)
            if key == "workflow":
                data["graph_recall"] = False
            return data

        self._patch(regulation_match, "settings", SimpleNamespace(app_config=cfg))

    def disable_rules(self):
        from src.core.agents.nodes import rule_scan
        from src.core.rule_engine import RuleHit

        class _NullScanner:
            @staticmethod
            def scan(blocks, rules, domain=None):
                return []

        self._patch(rule_scan, "rule_scanner", _NullScanner())
        _ = RuleHit  # noqa: F841  保持与节点同名导入可见（扫描返回空即规则路关闭）

    def disable_llm(self):
        from src.core.agents.nodes import llm_scan

        self._patch(llm_scan, "get_llm", lambda: None)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().parent / "variant_cases.json"),
        help="样本集 JSON（默认变体集）",
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 例（0=全部）")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径")
    parser.add_argument(
        "--arms", default="full,no_graph,no_rule", help="逗号分隔的对照臂（可加 no_llm）"
    )
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        print("未配置 DASHSCOPE_API_KEY，无法跑全链路消融（exit 2）")
        return 2

    # 全链路各臂经 evaluate → llm_scan.get_llm() 取客户端，包上运行级记账层
    from src.core.agents.nodes import llm_scan as _llm_scan

    _orig_get_llm = _llm_scan.get_llm
    _llm_scan.get_llm = lambda: recording_llm(_orig_get_llm())

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = data["cases"][: args.limit] if args.limit else data["cases"]
    ev = _load_module("evaluate_for_ablation", _EVALUATE_PATH)
    bc = _load_module("baseline_for_ablation", _BASELINE_PATH)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    results: dict[str, list[dict]] = {arm: [] for arm in arms}
    ab = _Ablation()

    for idx, case in enumerate(cases, start=1):
        for arm in arms:
            ab.restore()
            if arm == "no_graph":
                ab.disable_graph()
            elif arm == "no_rule":
                ab.disable_rules()
            elif arm == "no_llm":
                ab.disable_llm()
            elif arm != "full":
                print(f"未知对照臂: {arm}")
                return 2
            try:
                findings = ev._scan_full(case)
            finally:
                ab.restore()
            results[arm].append(bc.score_findings(findings, case))
        print(f"[{idx}/{len(cases)}] {case['id']} 完成")

    def _agg(rs: list[dict]) -> dict:
        gt = sum(r["gt_count"] for r in rs)
        tp = sum(r["tp_gt"] for r in rs)
        found = sum(r["found_count"] for r in rs)
        fp = sum(r["fp"] for r in rs)
        return {
            "recall": round(tp / gt, 4) if gt else 1.0,
            "fpr": round(fp / found, 4) if found else 0.0,
            "found": found,
            "fp": fp,
            "tp_gt": tp,
            "gt": gt,
        }

    gt_points = sum(len(c.get("ground_truth") or []) for c in cases)
    print(f"\n消融对照（样本 {len(cases)} 案例 / 标注点 {gt_points}）")
    print(f"{'对照臂':<12}{'召回率':>10}{'误报率':>10}{'检出':>8}{'误报数':>8}{'命中标注':>10}")
    print("-" * 66)
    summary = {arm: _agg(rs) for arm, rs in results.items()}
    for arm in arms:
        s = summary[arm]
        print(
            f"{arm:<12}{_fmt_pct(s['recall']):>10}{_fmt_pct(s['fpr']):>10}"
            f"{s['found']:>8}{s['fp']:>8}{s['tp_gt']:>10}"
        )
    if "full" in summary:
        for arm in arms:
            if arm == "full":
                continue
            delta = summary["full"]["recall"] - summary[arm]["recall"]
            print(f"贡献度 {arm}: 关闭后召回 {delta:+.1%}")
    print("\n注：no_llm 等价纯规则口径（图谱路只影响 LLM 上下文，不影响规则命中）。")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {"cases_file": str(args.cases), "case_count": len(cases), "arms": summary},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n明细已写入 {args.out}")
    print_cost_summary("ablation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
