"""旧/新引擎同语料对照（代码切换 A/B）：同一文档在旧镜像与新镜像下的产出对比。

背景：2026-10-24 跑批中途发现容器镜像停留在四批能力上线前（10-22），热切换镜像后，
把已完成的两份真实材料（fund_05 / insurance_01）以新代码补跑——构成同语料
旧/新对照对。本工具把对照变成可引用的数字：

- 成本：tokens / cost_ms（llm_scan stage detail）；
- 新能力上镜证据：channel（强度分级）/ precedents（先例注入数）——旧侧恒为空；
- 判定差异：按归一化文本匹配（含 2-gram Jaccard 兜底）对齐两版 findings，
  输出 kept / added / removed 与 kept 的 severity·confidence 漂移。

用法：
    uv run python scripts/evaluate/engine_ab_diff.py            # 默认两对已知对照
    uv run python scripts/evaluate/engine_ab_diff.py --pairs 987655380:987655386
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.models import ReviewResult  # noqa: E402
from src.models.task import ReviewTask  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent / "reports"

_DEFAULT_PAIRS = [("987655380", "987655386"), ("987655381", "987655387")]


def _norm(text: str) -> str:
    return "".join((text or "").split())


def _bigrams(text: str) -> set[str]:
    t = _norm(text)
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _similar(a: str, b: str, threshold: float = 0.5) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / len(ga | gb) >= threshold


def _load_task(db, tid: int):
    task = db.get(ReviewTask, tid)
    if task is None:
        return None, []
    rows = (
        db.query(ReviewResult)
        .filter(ReviewResult.task_id == tid)
        .order_by(ReviewResult.id)
        .all()
    )
    return task, rows


def _llm_detail(task) -> dict:
    stages = task.stages or {}
    return (stages.get("llm_scan") or {}).get("detail") or {}


def diff_pair(db, old_id: int, new_id: int) -> dict:
    old_task, old_rows = _load_task(db, old_id)
    new_task, new_rows = _load_task(db, new_id)
    out = {"old_task": old_id, "new_task": new_id}
    if old_task is None or new_task is None:
        out["error"] = "任务不存在"
        return out
    out["document_name"] = new_task.document_name
    out["status"] = {"old": old_task.status, "new": new_task.status}
    if old_task.status != "completed" or new_task.status != "completed":
        out["error"] = "对照需两侧都 completed（新侧补跑完成后重跑本工具）"
        return out

    od, nd = _llm_detail(old_task), _llm_detail(new_task)
    out["cost"] = {
        "old": {"tokens": od.get("tokens"), "cost_ms": od.get("cost_ms"),
                "finding_count": od.get("finding_count")},
        "new": {"tokens": nd.get("tokens"), "cost_ms": nd.get("cost_ms"),
                "finding_count": nd.get("finding_count"),
                "channel": nd.get("channel"), "precedents": nd.get("precedents")},
    }
    out["rule_hits"] = {
        "old": ((old_task.stages or {}).get("rule_scan") or {}).get("detail", {}).get("hit_count"),
        "new": ((new_task.stages or {}).get("rule_scan") or {}).get("detail", {}).get("hit_count"),
    }

    used: set[int] = set()
    kept, added_old = [], []
    for r_new in new_rows:
        m = next(
            (r_old for i, r_old in enumerate(old_rows)
             if i not in used and _similar(r_new.original_text or "", r_old.original_text or "")),
            None,
        )
        if m is not None:
            used.add(old_rows.index(m))
            kept.append({
                "text": (r_new.original_text or "")[:60],
                "severity": {"old": m.risk_level, "new": r_new.risk_level},
                "confidence": {"old": float(m.confidence_score or 0),
                               "new": float(r_new.confidence_score or 0)},
            })
        else:
            added_old.append({  # 新版新增检出
                "text": (r_new.original_text or "")[:60],
                "severity": r_new.risk_level,
                "description": (r_new.description or "")[:80],
            })
    removed = [  # 旧版有、新版没有（被先例/验证/新版判定移除）
        {"text": (r_old.original_text or "")[:60], "severity": r_old.risk_level}
        for i, r_old in enumerate(old_rows) if i not in used
    ]
    out["findings"] = {
        "old_total": len(old_rows), "new_total": len(new_rows),
        "kept": len(kept), "added_in_new": added_old, "removed_in_new": removed,
        "kept_drift": kept,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs", nargs="*", default=None,
        help="旧:新 任务对（默认 fund_05 与 insurance_01 两对）",
    )
    args = parser.parse_args()
    pairs = args.pairs or [f"{a}:{b}" for a, b in _DEFAULT_PAIRS]

    db = SessionLocal()
    try:
        report = {"ran_at": datetime.now().isoformat(timespec="seconds"), "pairs": []}
        ok = 0
        for p in pairs:
            old_s, _, new_s = p.partition(":")
            d = diff_pair(db, int(old_s), int(new_s))
            report["pairs"].append(d)
            if "error" in d:
                print(f"[{p}] 跳过：{d['error']}")
                continue
            ok += 1
            f, c = d["findings"], d["cost"]
            added_n, removed_n = len(f["added_in_new"]), len(f["removed_in_new"])
            print(
                f"[{p}] {d['document_name'][:30]}: 判定 {f['old_total']}→{f['new_total']}"
                f"（保留 {f['kept']} / 新增 {added_n} / 移除 {removed_n}）"
                f"；tokens {c['old']['tokens']}→{c['new']['tokens']}"
                f"；channel={c['new'].get('channel')} precedents={c['new'].get('precedents')}"
            )
        REPORT_DIR.mkdir(exist_ok=True)
        out_path = REPORT_DIR / f"engine_ab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告 → {out_path}")
        return 0 if ok else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
