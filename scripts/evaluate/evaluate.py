"""准确率评估脚本（PRD §14 测试策略 / §9 KPI）。

加载人工标注基准集，对每份样本文档跑审查，将系统检出与人工标注做文本重叠匹配，
计算召回率 / 精确率 / 误报率（整体 + 分领域 + 分检出来源），并输出逐条明细。

用法:
    python scripts/evaluate/evaluate.py
    python scripts/evaluate/evaluate.py --engine rule            # 仅规则引擎（快，无需 LLM key）
    python scripts/evaluate/evaluate.py --engine full            # 完整 workflow（含 LLM 语义审查）
    python scripts/evaluate/evaluate.py --cases data/eval/cases.json \
        --min-recall 0.91 --max-fpr 0.15

--engine:
    rule  按样本声明的 domain 过滤规则做扫描，隔离规则检测质量（不含领域分类与 LLM）。
    full  跑真实 LangGraph workflow（含关键词领域分类 + 混合检索 + LLM），反映系统真实行为。
--min-recall / --max-fpr: 给定时指标不达标则退出码非 0（CI / 上线门禁）。

指标口径:
    召回率 recall = 被至少一条系统检出命中的标注点数 / 标注点总数
    误报率 fpr   = 未命中任何标注点的系统检出数 / 系统检出总数
    精确率 precision = 1 - fpr
匹配规则: 任一系统检出的原文片段与标注片段互为子串即算命中（与 conflict_resolve._overlaps 一致）。
"""

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows 控制台默认 GBK 打不出部分 Unicode（✓/✗ 等），统一强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
# 评估只看指标，静默 SQL echo 日志（覆盖 sqlalchemy.engine / pool / dialect 整棵子树）
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.agents.graph import run_review
from src.core.rule_engine import RuleHit, rule_scanner
from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.database.mysql import engine as _engine
from src.models import Rule
from src.parsers.base import TextBlock
from src.utils.config import settings

# SQLAlchemy InstanceLogger 按 echo 标志绕过 logger 级别（_echo_map[echo]=INFO），
# 只设 logger level 压不住，需直接把 engine echo 关掉，避免评估输出被 SQL 刷屏。
_engine.logger.echo = False


def _overlaps(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a in b or b in a


def _blocks_from_text(text: str) -> list[dict]:
    """把样本全文拆为块（按行），保留 page/paragraph 位置供定位。"""
    blocks = []
    for i, line in enumerate(text.splitlines() or [text]):
        line = line.strip()
        if line:
            blocks.append({"text": line, "page": 1, "paragraph": i + 1, "heading": False})
    return blocks


def _load_active_rules() -> list:
    db = SessionLocal()
    try:
        return db.query(Rule).filter(Rule.is_active == 1).all()
    finally:
        db.close()


def _scan_rule_engine(case: dict) -> list[dict]:
    """仅规则引擎：按样本 domain 过滤，隔离规则检测质量。

    命中原文取精确关键词 span（RuleHit.char_start:char_end），不用加窗 evidence
    片段——窗口会覆盖相邻文本导致匹配过宽。窗口文本保留在 window_text 供诊断。
    """
    rules = _load_active_rules()
    min_conf = settings.app_config("rule_engine").get("min_confidence", 0.5)

    findings = []
    for line in case["text"].splitlines() or [case["text"]]:
        line = line.strip()
        if not line:
            continue
        block = TextBlock(text=line, page=1, paragraph=1, heading=False)
        hits: list[RuleHit] = rule_scanner.scan([block], rules, domain=case.get("domain"))
        if min_conf > 0:
            hits = [h for h in hits if h.confidence >= min_conf]
        for h in hits:
            findings.append(
                {
                    "source": "rule",
                    "rule_name": h.rule_name,
                    "original_text": line[h.char_start:h.char_end],
                    "window_text": h.matched_text,
                    "page": h.page,
                    "paragraph": h.paragraph,
                    "confidence": h.confidence,
                }
            )
    return findings


def _scan_full(case: dict) -> list[dict]:
    """完整 workflow：领域分类 + 法规匹配 + 规则引擎 ∥ LLM + 冲突融合 + 风险定级。"""
    result = run_review(
        {
            # 评估用虚拟 task_id，避免落盘冲突
            "task_id": int(1e9) + abs(hash(case["id"])) % 10_0000,
            "document_name": case.get("document_name", case["id"]),
            "document_path": f"/eval/{case['id']}.txt",
            "doc_type": "txt",
            "text": case["text"],
            "blocks": _blocks_from_text(case["text"]),
        }
    )
    return list((result.get("report") or {}).get("violations", []))


def _evaluate_case(case: dict, engine: str) -> dict:
    gt = case.get("ground_truth", [])
    findings = _scan_rule_engine(case) if engine == "rule" else _scan_full(case)

    matched_gt = set()
    fp = 0
    hit_details = []
    for _i, f in enumerate(findings):
        text = f.get("original_text") or ""
        matched = [g for j, g in enumerate(gt) if _overlaps(text, g.get("text", ""))]
        if matched:
            matched_gt.update(id(g) for g in matched)
            for g in matched:
                hit_details.append((g, f))
        else:
            fp += 1

    recall = len(matched_gt) / len(gt) if gt else 1.0  # 无标注样本：无遗漏即 1.0
    precision = (len(findings) - fp) / len(findings) if findings else 1.0
    return {
        "id": case["id"],
        "domain": case.get("domain"),
        "ground_truth": gt,
        "gt_count": len(gt),
        "found_count": len(findings),
        "tp_gt": len(matched_gt),
        "fp": fp,
        "recall": recall,
        "precision": precision,
        "fpr": 1 - precision,
        "source_counter": Counter(f.get("source", "?") for f in findings),
        "findings": findings,
        "hit_details": hit_details,
    }


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(Path(__file__).parent / "eval_cases.json"))
    parser.add_argument("--engine", choices=["rule", "full"], default="full")
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument("--max-fpr", type=float, default=None)
    parser.add_argument("--top", type=int, default=8, help="每份样本最多展示 N 条检出明细")
    args = parser.parse_args()

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = data["cases"]

    results = [_evaluate_case(c, args.engine) for c in cases]

    # ---- 整体 / 分领域 / 分来源汇总 ----
    all_gt = sum(r["gt_count"] for r in results)
    all_tp = sum(r["tp_gt"] for r in results)
    all_found = sum(r["found_count"] for r in results)
    all_fp = sum(r["fp"] for r in results)

    by_domain = defaultdict(lambda: {"gt": 0, "tp": 0, "found": 0, "fp": 0})
    by_source = defaultdict(lambda: {"found": 0, "fp": 0})
    for r in results:
        d = by_domain[r["domain"] or "unknown"]
        d["gt"] += r["gt_count"]
        d["tp"] += r["tp_gt"]
        d["found"] += r["found_count"]
        d["fp"] += r["fp"]
        for src, n in r["source_counter"].items():
            by_source[src]["found"] += n
            # 无法逐来源区分 FP，仅标注 rule 口径
            by_source[src]["fp"] += r["fp"] if src == "rule" else 0

    recall = all_tp / all_gt if all_gt else 1.0
    fpr = all_fp / all_found if all_found else 0.0
    precision = 1 - fpr

    print(f"引擎: {args.engine} | 样本: {len(cases)} 份（标注点 {all_gt}） | 基准集: {args.cases}")
    print(f"{'=' * 66}")
    print(f"{'指标':<10}{'整体':>10}{'banking':>10}{'fund':>10}{'insurance':>10}")
    for name, fn in [("召回率", lambda d: d["tp"] / d["gt"] if d["gt"] else 1.0),
                     ("误报率", lambda d: d["fp"] / d["found"] if d["found"] else 0.0)]:
        row = f"{name:<10}"
        for key in ["整体", "banking", "fund", "insurance"]:
            if key == "整体":
                val = recall if name == "召回率" else fpr
            else:
                d = by_domain[key]
                val = fn(d)
            row += f"{_fmt_pct(val):>10}"
        print(row)
    print(f"{'-' * 66}")
    print(
        f"系统检出: {all_found} 条 | 命中标注: {all_tp} | 误报: {all_fp} | "
        f"精确率: {_fmt_pct(precision)}"
    )
    print(f"检出来源分布: {dict(by_source)}")

    # ---- 逐条明细 ----
    print(f"\n{'=' * 66}\n逐条明细:")
    for r in results:
        status = "PASS" if r["recall"] == 1.0 and r["fpr"] == 0.0 else "FAIL"
        line = (
            f"\n{status} [{r['id']}] ({r['domain']}) 标注 {r['gt_count']} "
            f"/ 检出 {r['found_count']} / 召回 {_fmt_pct(r['recall'])} "
            f"/ 误报 {_fmt_pct(r['fpr'])} / 来源 {dict(r['source_counter'])}"
        )
        print(line)
        for g, f in r["hit_details"][: args.top]:
            print(f"    + 标注命中: 「{g.get('text')}」 ← [{f.get('source')}] {f.get('rule_name')} "
                  f"(conf={f.get('confidence')})")
        fp_show = [
            f.get("original_text") for f in r["findings"]
            if not any(
                _overlaps(f.get("original_text", ""), g.get("text", ""))
                for g in r["ground_truth"]
            )
        ]
        for t in fp_show[: args.top]:
            print(f"    - 误报: 「{t}」")

    # ---- 门禁 ----
    print(f"\n{'=' * 66}")
    fail = False
    if args.min_recall is not None and recall < args.min_recall:
        print(f"FAIL: 召回率 {_fmt_pct(recall)} < 目标 {_fmt_pct(args.min_recall)}")
        fail = True
    if args.max_fpr is not None and fpr > args.max_fpr:
        print(f"FAIL: 误报率 {_fmt_pct(fpr)} > 上限 {_fmt_pct(args.max_fpr)}")
        fail = True
    print(
        f"结论: 召回率 {_fmt_pct(recall)} / 误报率 {_fmt_pct(fpr)} / 精确率 {_fmt_pct(precision)}"
    )
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
