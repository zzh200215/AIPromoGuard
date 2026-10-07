"""方向③ 数据闭环·回流任务：把线上人工复核反馈（确认/误报）回流进评估基准集并触发门禁。

把评估从「CI 里的一次性跑」升级成「活的门禁 + 数据闭环」：

[流程]
1. 抽查（checkpoint 水位）：只拉 `confirmed_by>0 且 confirmed_at ≥ 上次水位` 的人工复核结果，
   水位按确认时间推进——翻案（confirmed↔false_positive 刷新 confirmed_at）也会被重新吸收。
2. 建带标注样本（按 review_task 聚合）：全 confirmed → 正例；全 false_positive → 负面；
   混合任务 → ground_truth(confirmed) + negative_ground_truth(false_positive)，
   不再像旧 export_labels 一样整份跳过——人工确认的误报片段直接进回归基准集。
3. 只增不减的 registry 去重合并：
   - registry.json 是唯一事实源（合成种子 + 真实复核，带指纹/血统/来源），案例只增不减；
   - 同一任务再次复核（翻案）以最新判定就地刷新标签；
   - 不同任务同文档仅并入血统，不重复加案。
4. 产出两份评估集：
   - full_cases.json：全部 confirmed 标注（供 `--engine full` 全链路评估）；
   - gate_cases.json：只投影 rule/hybrid 来源的标注（供 `--engine rule` 规则门禁）——
     若确认项全是 LLM 独有，规则引擎本就不该命中，投影掉它避免规则门禁误红。
5. 触发门禁：跑 `evaluate.py --engine rule --cases gate_cases.json`，指标跌破即非零退出。
6. 规则健康打标：按规则聚合误报率，复用 rule_tuning 建议（deactivate/remove_keyword/
   set_threshold），并给出全局 min_confidence 收紧建议（仅展示，不自动改配置）。

[幂等] 脚本可按 cron 周期跑：水位推进 + 指纹去重 → 重复执行不产生重复样本。

用法:
    python scripts/evaluate/reflow_labels.py                  # 完整闭环（需 DB + 规则导入）
    python scripts/evaluate/reflow_labels.py --seed-only      # 仅合成种子初始化 registry（无需 DB）
    python scripts/evaluate/reflow_labels.py --dry-run        # 只算不写
    python scripts/evaluate/reflow_labels.py --skip-gate      # 回流但不跑门禁
    python scripts/evaluate/reflow_labels.py --max-fpr 0.05   # 覆盖门禁误报率上限
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import func

# Windows 控制台默认 GBK 打不出部分 Unicode，统一强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.models import ReviewResult, ReviewTask, Rule  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SEED = Path(__file__).resolve().parent / "eval_cases.json"
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "registry.json"
DEFAULT_OUT_GATE = Path(__file__).resolve().parent / "gate_cases.json"
DEFAULT_OUT_FULL = Path(__file__).resolve().parent / "full_cases.json"
DEFAULT_CHECKPOINT = REPO_ROOT / "data" / "eval" / ".reflow-checkpoint.json"

# 与数据清理一致的测试标记（人工复核 notes），防止开发期噪声污染真实标注集
_TEST_MARKERS = ("测试人工复核", "E2E", "e2e")
_WHITESPACE_RE = re.compile(r"\s+")

# 规则门禁只信用 rule/hybrid 来源的确认标注（hybrid = 规则∩LLM，规则引擎必命中）
_RULE_GATE_SOURCES = {"rule", "hybrid"}


# ---------- 纯函数（可单测，不依赖 DB） ----------

def fingerprint(text: str) -> str:
    """文档指纹：去空白后 sha256，用于跨任务去重（同一文档只算一份）。"""
    normalized = _WHITESPACE_RE.sub("", text or "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def read_document_text(document_path: str | None) -> str | None:
    """按 DB 里的 document_path 读源文档原文（兼容 \\ 分隔符，相对仓库根解析）。"""
    if not document_path:
        return None
    p = Path(document_path.replace("\\", "/"))
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_test_row(description: str | None) -> bool:
    return any(m in (description or "") for m in _TEST_MARKERS)


def _seed_case(c: dict) -> dict:
    """合成基准样本 → registry case（标注视为 rule 来源，供规则门禁投影）。"""
    gt = []
    for g in c.get("ground_truth") or []:
        item = {"text": g["text"], "rule_name": g.get("rule_name", ""),
                "risk_level": g.get("risk_level", "medium"), "source": "rule"}
        if item not in gt:
            gt.append(item)
    return {
        "id": c["id"],
        "case_key": f"syn:{c['id']}",
        "domain": c.get("domain", "unknown"),
        "text": c.get("text", ""),
        "fingerprint": fingerprint(c.get("text", "")),
        "ground_truth": gt,
        "negative_ground_truth": [],
        "origin": "synthetic",
        "lineage": {"task_ids": [], "result_ids": [], "first_seen": None,
                    "last_reviewed_at": None},
    }


def build_task_case(task_id: int, rows: list[dict], text: str, domain: str) -> dict:
    """一组复核行（同一任务）→ 标注样本 case。

    confirmed → ground_truth；false_positive → negative_ground_truth（不进召回、检出即误报）。
    """
    confirmed, negatives = [], []
    result_ids = []
    for r in rows:
        result_ids.append(r["result_id"])
        if r["status"] == "confirmed":
            item = {
                "text": r["original_text"],
                "rule_name": r["rule_name"] or "",
                "risk_level": r["risk_level"] or "medium",
                "source": r["violation_type"],
            }
            if item not in confirmed:
                confirmed.append(item)
        elif r["status"] == "false_positive":
            item = {"text": r["original_text"], "rule_name": r["rule_name"] or ""}
            if item not in negatives:
                negatives.append(item)

    now_iso = datetime.now().isoformat(timespec="seconds")
    return {
        "id": f"hr_{task_id}",
        "case_key": f"hr:{task_id}",
        "domain": domain,
        "text": text,
        "fingerprint": fingerprint(text),
        "ground_truth": confirmed,
        "negative_ground_truth": negatives,
        "origin": "human_review",
        "lineage": {
            "task_ids": [task_id],
            "result_ids": result_ids,
            "first_seen": now_iso,
            "last_reviewed_at": now_iso,
        },
    }


def _merge_lineage(old: dict, new: dict) -> dict:
    lo, ln = old["lineage"], new["lineage"]
    return {
        "task_ids": sorted(set(lo.get("task_ids", []) + ln.get("task_ids", []))),
        "result_ids": sorted(set(lo.get("result_ids", []) + ln.get("result_ids", []))),
        "first_seen": lo.get("first_seen") or ln.get("first_seen"),
        "last_reviewed_at": ln.get("last_reviewed_at") or lo.get("last_reviewed_at"),
    }


def merge_cases(
    registry: list[dict], new_cases: list[dict]
) -> tuple[list[dict], list[str], list[str]]:
    """只增不减合并：同 case_key 翻案就地刷新；同指纹异任务并入血统；全新则追加。

    返回 (案例列表, 新增 id 列表, 更新 id 列表)。案例永不删除。
    """
    by_key = {c["case_key"]: i for i, c in enumerate(registry)}
    by_fp = {c["fingerprint"]: i for i, c in enumerate(registry)}
    added, updated = [], []

    for nc in new_cases:
        idx = by_key.get(nc["case_key"])
        if idx is not None:  # 同一 review_task 再复核（含翻案）→ 以最新判定替换标签
            old = registry[idx]
            old["ground_truth"] = nc["ground_truth"]
            old["negative_ground_truth"] = nc["negative_ground_truth"]
            old["lineage"] = _merge_lineage(old, nc)
            updated.append(old["id"])
        else:
            idx = by_fp.get(nc["fingerprint"])
            if idx is not None:  # 不同任务同一文档 → 只并入血统，不重复加案
                old = registry[idx]
                old["lineage"] = _merge_lineage(old, nc)
                if old["origin"] == "synthetic" and nc["ground_truth"]:
                    old["ground_truth"] = old["ground_truth"] + nc["ground_truth"]
                updated.append(old["id"])
            else:  # 全新案例 → 追加（只增不减）
                by_key[nc["case_key"]] = len(registry)
                by_fp[nc["fingerprint"]] = len(registry)
                registry.append(nc)
                added.append(nc["id"])
    return registry, added, updated


def project_gate_cases(cases: list[dict]) -> list[dict]:
    """规则门禁投影：只保留 rule/hybrid 来源的确认标注 + 全部负面标注 + 合成负面样本。

    保留规则：
    - 有 rule/hybrid 确认标注 → 正常规则召回样本；
    - 有负面标注（人工判定误报片段）→ 守误报（检出即 FP）；
    - 合成集里 ground_truth 为空的「干净文档」→ 本就是守误报的负面样本，必须保留；
    - 只有 LLM 独有确认（无 rule 标注、无负面）→ 不投影进规则门禁，规则引擎本就不该命中。
    """
    gate = []
    for c in cases:
        gt_rule = [g for g in c.get("ground_truth") or [] if g.get("source") in _RULE_GATE_SOURCES]
        negatives = c.get("negative_ground_truth") or []
        synthetic_negative = c.get("origin") == "synthetic" and not c.get("ground_truth")
        if not gt_rule and not negatives and not synthetic_negative:
            continue
        gate.append(
            {
                "id": c["id"],
                "domain": c.get("domain", "unknown"),
                "text": c.get("text", ""),
                "ground_truth": [{k: g[k] for k in ("text", "rule_name", "risk_level") if k in g}
                                 for g in gt_rule],
                "negative_ground_truth": negatives,
            }
        )
    return gate


def to_full_case(c: dict) -> dict:
    """registry case → 全量评估格式（供 --engine full 全链路评估）。"""
    return {
        "id": c["id"],
        "domain": c.get("domain", "unknown"),
        "text": c.get("text", ""),
        "ground_truth": [{k: g[k] for k in ("text", "rule_name", "risk_level") if k in g}
                         for g in c.get("ground_truth") or []],
        "negative_ground_truth": c.get("negative_ground_truth") or [],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- DB 阶段 ----------

def query_reviewed_rows(since_iso: str | None):
    """抽取人工复核反馈（confirmed_by>0）。水位取时间，翻案会刷新 confirmed_at 再被吸收。"""
    db = SessionLocal()
    try:
        cond = [ReviewResult.confirmed_by.isnot(None), ReviewResult.confirmed_by > 0]
        if since_iso:
            cond.append(ReviewResult.confirmed_at >= since_iso)
        rows = (
            db.query(
                ReviewResult.id, ReviewResult.task_id, ReviewResult.original_text,
                ReviewResult.status, ReviewResult.violation_type, ReviewResult.risk_level,
                ReviewResult.confirmed_at, ReviewResult.description,
            )
            .join(ReviewTask, ReviewTask.id == ReviewResult.task_id, isouter=True)
            .outerjoin(Rule, Rule.id == ReviewResult.rule_id)
            .add_columns(
                Rule.rule_name, Rule.domain.label("rule_domain"),
                ReviewTask.document_path, ReviewTask.domain.label("task_domain"),
            )
            .filter(*cond)
            .order_by(ReviewResult.confirmed_at, ReviewResult.id)
            .all()
        )
        # Row → dict（id 改名 result_id），供纯函数复用
        out = []
        for r in rows:
            d = dict(r._mapping)
            d["result_id"] = d.pop("id")
            out.append(d)
        return out
    finally:
        db.close()


def _group_by_task(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["task_id"] or 0].append(r)
    return grouped


def rule_health_report(db) -> dict:
    """按规则聚合人工复核（口径同 rules/quality），并附 rule_tuning 的自动打标建议。"""
    from src.services.rule_tuning import build_rule_suggestions

    rows = (
        db.query(ReviewResult.rule_id, ReviewResult.status, func.count(ReviewResult.id))
        .filter(
            ReviewResult.rule_id.isnot(None),
            ReviewResult.confirmed_by.isnot(None),
            ReviewResult.confirmed_by > 0,
        )
        .group_by(ReviewResult.rule_id, ReviewResult.status)
        .all()
    )
    acc: dict[int, dict[str, int]] = {}
    for rule_id, status, count in rows:
        acc.setdefault(rule_id, {"confirmed": 0, "false_positive": 0})[status] = count
    rule_names = {r.id: r.rule_name for r in db.query(Rule.id, Rule.rule_name).all()}
    suggestions = build_rule_suggestions(db)
    flag_by_rule = {s["rule_id"]: s for s in suggestions}

    items = []
    for rule_id, bucket in acc.items():
        reviewed = bucket["confirmed"] + bucket["false_positive"]
        if reviewed == 0:
            continue
        fp_rate = bucket["false_positive"] / reviewed
        sug = flag_by_rule.get(rule_id)
        items.append(
            {
                "rule_id": rule_id,
                "rule_name": rule_names.get(rule_id),
                "confirmed": bucket["confirmed"],
                "false_positive": bucket["false_positive"],
                "fp_rate": round(fp_rate, 3),
                "action": sug["action"] if sug else "ok",
                "detail": sug["reason"] if sug else "",
                "threshold": sug.get("threshold") if sug else None,
            }
        )
    items.sort(key=lambda x: x["fp_rate"], reverse=True)
    return items


# ---------- 主流程 ----------

def main() -> int:
    formatter = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=formatter)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="合成基准集（种子）")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-gate", type=Path, default=DEFAULT_OUT_GATE)
    parser.add_argument("--out-full", type=Path, default=DEFAULT_OUT_FULL)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--min-recall", type=float, default=0.98)
    parser.add_argument("--max-fpr", type=float, default=0.02)
    parser.add_argument("--skip-gate", action="store_true", help="回流但不触发门禁")
    parser.add_argument("--seed-only", action="store_true", help="仅初始化 registry（无需 DB）")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写任何文件")
    args = parser.parse_args()

    # 1) 载入 registry
    if args.registry.exists():
        registry = json.loads(args.registry.read_text(encoding="utf-8"))["cases"]
    else:
        registry = []

    if args.seed.exists():
        seed = json.loads(args.seed.read_text(encoding="utf-8"))
    else:
        seed = {"cases": []}
    seed_cases = [_seed_case(c) for c in seed.get("cases", [])]
    registry, add_seed, upd_seed = merge_cases(registry, seed_cases)

    # 2) 人工复核反馈回流（DB 不可用则降级为仅种子）
    ingest_notes, new_watermark = [], None
    if args.seed_only:
        pass
    else:
        try:
            checkpoint = {}
            if args.checkpoint.exists():
                checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
            since = checkpoint.get("last_confirmed_at")
            rows = query_reviewed_rows(since)
            if rows:
                new_watermark = max(str(r["confirmed_at"] or "") for r in rows)
            grouped = _group_by_task(rows)
            new_cases = []
            skipped = {"test": 0, "unreadable": 0, "empty": 0}
            for task_id in sorted(grouped):
                task_rows = grouped[task_id]
                if any(_is_test_row(r.get("description")) for r in task_rows):
                    skipped["test"] += 1
                    continue
                doc = next((r["document_path"] for r in task_rows if r.get("document_path")), None)
                text = read_document_text(doc)
                if not text:
                    skipped["unreadable"] += 1
                    continue
                task_domain = next(
                    (r["task_domain"] for r in task_rows if r.get("task_domain")), None
                )
                rule_domain = next(
                    (r["rule_domain"] for r in task_rows if r.get("rule_domain")), None
                )
                domain = task_domain or rule_domain or "unknown"
                new_cases.append(build_task_case(task_id, task_rows, text, domain))
            registry, add_ids, upd_ids = merge_cases(registry, new_cases)
            ingest_notes = [f"新增 {len(add_ids)} / 更新 {len(upd_ids)}（含翻案）"]
            if sum(skipped.values()):
                ingest_notes.append(f"跳过 {dict(skipped)}")
        except Exception as exc:  # DB 不可用等 → 不阻断种子初始化
            ingest_notes = [f"DB 不可用，跳过真实复核回流（{type(exc).__name__}: {exc}）"]

    # 3) 写回产物（dry-run 不写）
    full_cases = [to_full_case(c) for c in registry]
    gate_cases = project_gate_cases(registry)
    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(full_cases),
        "gate_case_count": len(gate_cases),
    }
    if not args.dry_run:
        _write_json(args.registry, {**payload, "cases": registry})
        _write_json(args.out_full, payload | {"cases": full_cases})
        _write_json(args.out_gate, payload | {"cases": gate_cases})
        if new_watermark:
            args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            cp = {"last_confirmed_at": new_watermark, "updated_at": payload["updated_at"]}
            args.checkpoint.write_text(
                json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    print(f"评估集: 合成 {len(seed_cases)}（新增种子 {len(add_seed)}）| "
          f"registry 共 {len(registry)} 案例 | full {len(full_cases)} | gate {len(gate_cases)}")
    if ingest_notes:
        print("回流: " + "；".join(ingest_notes))
    if args.dry_run:
        print("[dry-run] 未写任何文件")

    # 4) 规则健康打标（自动给高误报规则打「下架/移词/调阈值」标）
    if not args.seed_only:
        try:
            db = SessionLocal()
            try:
                health = rule_health_report(db)
            finally:
                db.close()
            if health:
                print("\n按规则误报率（人工复核口径，高误报优先）:")
                for h in health[:10]:
                    act = h["action"]
                    tag = {
                        "deactivate": "建议下架",
                        "remove_keyword": "建议移词",
                        "set_threshold": f"建议调阈值 {h.get('threshold')}",
                    }.get(act, "ok")
                    print(f"  {h['rule_id']:>5} {h['rule_name']:<20} "
                          f"确认 {h['confirmed']} / 误报 {h['false_positive']} "
                          f"误报率 {h['fp_rate']:.0%}  {tag}")
                thr = [h.get("threshold") for h in health if h.get("threshold") is not None]
                if thr:
                    med = sorted(thr)[len(thr) // 2]
                    print(f"\n全局建议: 如需整体收紧，可将 configs/app.yaml 的 "
                          "rule_engine.min_confidence 上调到 "
                          f"{med:.2f}（或对单规则应用 set_threshold）")
                print(f"完整打标见: {len(health)} 条（仅展示前 10）")
        except Exception as exc:
            print(f"规则健康打标跳过：{type(exc).__name__}: {exc}")

    # 5) 触发门禁（对 gate 集跑规则引擎；seed-only 无 DB、无新增样本，不触发）
    gate_exit = 0
    if args.skip_gate or args.dry_run or args.seed_only or not gate_cases:
        pass
    else:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "evaluate.py"),
            "--engine", "rule",
            "--cases", str(args.out_gate),
            "--min-recall", str(args.min_recall),
            "--max-fpr", str(args.max_fpr),
        ]
        print(f"\n触发门禁: {' '.join(cmd[-6:])}")
        gate_exit = subprocess.run(cmd, cwd=REPO_ROOT).returncode
        print(f"门禁: {'PASS' if gate_exit == 0 else 'FAIL'}")
    return gate_exit


if __name__ == "__main__":
    sys.exit(main())
