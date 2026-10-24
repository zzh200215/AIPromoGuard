"""Verifier A/B 对照：对已完成任务的已产判定跑一遍独立验证，量化验证器效果。

用途（第 3 批 Verifier 的效果证据，跑批结束后执行——每任务 +1 次 LLM 调用）：

- 数据源：review_results 里已落库的判定（含系统自动确认），重建为 findings，
  全部当作验证面（source=llm）——线上节点只验 source=llm 子集，本工具验全部，
  口径在报告中标注；
- 复用线上 verify() 全链路（同一提示词、同一驳回保守阈值、同一三态应用），
  通过 monkeypatch V._cfg 打开开关——工具与节点逻辑零漂移；
- 产出：upheld / downgraded / rejected（剔除 vs 保留）分布 + 被剔除判定明细，
  落盘 scripts/evaluate/reports/verifier_ab_<时间>.json。

用法：
    uv run python scripts/evaluate/verifier_ab.py --dry-run   # 零 LLM：只看样本量
    uv run python scripts/evaluate/verifier_ab.py             # 真跑（需 .env LLM key）
    uv run python scripts/evaluate/verifier_ab.py --limit 2   # 每任务最多验证 N 条
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.models import Article, Regulation, ReviewResult  # noqa: E402
from src.models.task import ReviewTask  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent / "reports"


def load_findings(db, task_min: int, task_ids=None, limit: int = 0):
    """把已落库判定重建为 findings（全部 source=llm → 全量进验证面）。"""
    q = (
        db.query(ReviewResult, ReviewTask.document_name)
        .join(ReviewTask, ReviewTask.id == ReviewResult.task_id)
        .filter(ReviewTask.status == "completed")
        .order_by(ReviewResult.task_id, ReviewResult.id)
    )
    if task_ids:
        q = q.filter(ReviewResult.task_id.in_(task_ids))
    else:
        q = q.filter(ReviewResult.task_id >= task_min)

    findings_by_task: dict[int, dict] = {}
    for r, doc_name in q.all():
        reg = None
        if r.article_id is not None:
            row = (
                db.query(Article, Regulation)
                .join(Regulation, Regulation.id == Article.regulation_id)
                .filter(Article.id == r.article_id)
                .first()
            )
            if row:
                art, rg = row
                reg = f"{rg.regulation_name} {art.article_no}"
        findings = findings_by_task.setdefault(
            r.task_id, {"document_name": doc_name, "findings": []}
        )
        if limit > 0 and len(findings["findings"]) >= limit:
            continue
        findings["findings"].append(
            {
                "type": r.violation_type or "",
                "issue": r.description or "",
                "original_text": r.original_text or "",
                "regulation": reg or "",
                "suggestion": r.suggestion or "",
                "severity": r.risk_level or "",
                "confidence": float(r.confidence_score or 0),
                "source": "llm",  # A/B 口径：全量验证面（线上仅 source=llm 子集）
                "result_id": r.id,
                "stored_status": r.status,
            }
        )
    return findings_by_task


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-min", type=int, default=987655364)
    parser.add_argument("--task-ids", type=int, nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=0, help="每任务最多 N 条（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="不调 LLM，只看样本量")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        findings_by_task = load_findings(db, args.task_min, args.task_ids, args.limit)
        total = sum(len(v["findings"]) for v in findings_by_task.values())
        print(f"可验证任务 {len(findings_by_task)} 个 / 判定 {total} 条（A/B 口径：全量验证面）")
        for tid, v in sorted(findings_by_task.items()):
            print(f"  task {tid} ({v['document_name'][:30]}): {len(v['findings'])} 条")
        if not findings_by_task or total == 0:
            print("无样本，结束")
            return 2
        if args.dry_run:
            print("dry-run 结束（未调用 LLM）")
            return 0

        import src.core.agents.nodes.verify as V

        V._cfg = lambda: {**V._DEFAULTS, "verifier": True}

        report = {
            "ran_at": datetime.now().isoformat(timespec="seconds"),
            "scope": "all stored findings as verification targets (prod: source=llm only)",
            "tasks": [],
        }
        agg = {"upheld": 0, "downgraded": 0, "rejected_dropped": 0,
               "rejected_kept": 0, "failed": 0, "verified": 0}
        for tid, v in sorted(findings_by_task.items()):
            state = {"merged_findings": v["findings"]}
            out = V.verify(state)
            meta = out.get("verification_meta") or {}
            kept = out.get("merged_findings", v["findings"])
            for k in agg:
                agg[k] += int(meta.get(k, 0))
            report["tasks"].append(
                {
                    "task_id": tid,
                    "document_name": v["document_name"],
                    "input": len(v["findings"]),
                    "kept": len(kept),
                    "meta": meta,
                    "verdicts": [
                        {"result_id": f.get("result_id"),
                         "stored_status": f.get("stored_status"),
                         "confidence": f.get("confidence"),
                         "verification": f.get("verification")}
                        for f in kept if f.get("verification")
                    ],
                }
            )
            print(
                f"  task {tid}: 输入 {len(v['findings'])} → 保留 {len(kept)}"
                f"（维持 {meta.get('upheld', 0)} / 降级 {meta.get('downgraded', 0)}"
                f" / 剔除 {meta.get('rejected_dropped', 0)} / 失败 {meta.get('failed', 0)}）"
            )

        report["aggregate"] = agg
        REPORT_DIR.mkdir(exist_ok=True)
        out_path = REPORT_DIR / f"verifier_ab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"汇总：{json.dumps(agg, ensure_ascii=False)}")
        print(f"报告 → {out_path}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
