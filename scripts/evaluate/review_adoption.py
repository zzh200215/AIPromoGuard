"""人工复核采纳率统计：把 review_results 的复核漏斗变成可汇报的系统级数字。

这是"AI 审查结果被合规人员接受或修改的比例"这一业务价值指标的数据出口，
口径与 /results/feedback-stats 保持一致：

- 人工复核 = confirmed_by > 0；系统自动确认（confirmed_by=0，方向②高置信分流）
  不计入采纳率分母，避免自动分流虚高确认率
- 采纳率 confirm_rate = 人工复核结论中 confirmed 占比
- 误报率 false_positive_rate = 人工复核结论中 false_positive 占比
- 自动确认覆盖率 = 自动确认条数 / 全部条数（衡量"人只看机器拿不准的"分流效果）
- 翻案率 = 审计事件（action=result.confirm）中 before_status != verdict 的占比；
  其中"纠错自动确认"子集 = before_auto_confirmed=true 的翻转。
  审计明细自 confirm 留痕（2026-08-29）起才有，此前仅 HTTP 层粗记录，不计入。

用法（仓库根目录）:
    python scripts/evaluate/review_adoption.py
    python scripts/evaluate/review_adoption.py --json adoption_report.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)

from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.infrastructure.database.mysql import engine as _engine  # noqa: E402
from src.models import AuditLog, ReviewResult  # noqa: E402
from src.utils.config import settings  # noqa: E402

_engine.logger.echo = False

_SOURCES = ("rule", "hybrid", "llm")


def adoption_stats(db) -> dict:
    """复核漏斗 + 采纳率 + 翻案率（只读查询，不落任何数据）。"""
    rows = (
        db.query(
            ReviewResult.violation_type,
            ReviewResult.status,
            ReviewResult.confirmed_by,
            ReviewResult.id,
        )
        .all()
    )

    total = len(rows)
    auto_confirmed = 0
    pending = 0
    human = {src: {"confirmed": 0, "false_positive": 0} for src in _SOURCES}
    for vtype, status, confirmed_by, _rid in rows:
        if confirmed_by == 0:
            auto_confirmed += 1
        elif confirmed_by is None:
            pending += 1
        elif status in ("confirmed", "false_positive") and vtype in human:
            human[vtype][status] += 1

    reviewed = sum(sum(b.values()) for b in human.values())
    human_confirmed = sum(b["confirmed"] for b in human.values())
    human_fp = sum(b["false_positive"] for b in human.values())

    by_source = {}
    for src, bucket in human.items():
        n = bucket["confirmed"] + bucket["false_positive"]
        by_source[src] = {
            "confirmed": bucket["confirmed"],
            "false_positive": bucket["false_positive"],
            "confirm_rate": round(bucket["confirmed"] / n, 3) if n else None,
        }

    overturn = _overturn_stats(db)
    return {
        "total_findings": total,
        "auto_confirmed": auto_confirmed,
        "auto_confirm_rate": round(auto_confirmed / total, 3) if total else None,
        "pending_confirm": pending,
        "human_reviewed": reviewed,
        "human_confirmed": human_confirmed,
        "human_false_positive": human_fp,
        "confirm_rate": round(human_confirmed / reviewed, 3) if reviewed else None,
        "false_positive_rate": round(human_fp / reviewed, 3) if reviewed else None,
        "by_source": by_source,
        "overturn": overturn,
    }


def _overturn_stats(db) -> dict:
    """翻案口径：审计明细中 before_status != verdict 的判定事件。"""
    rows = db.query(AuditLog.detail).filter(AuditLog.action == "result.confirm").all()
    events = flips = auto_corrections = 0
    for (detail,) in rows:
        if not detail:
            continue
        try:
            data = json.loads(detail)
        except json.JSONDecodeError:
            continue
        events += 1
        if data.get("before_status") != data.get("verdict"):
            flips += 1
            if data.get("before_auto_confirmed"):
                auto_corrections += 1
    return {
        "events": events,
        "flips": flips,
        "auto_corrections": auto_corrections,
        "overturn_rate": round(flips / events, 3) if events else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_out", default=None, help="结果另存 JSON 文件")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = adoption_stats(db)
    finally:
        db.close()

    print(f"复核漏斗（口径与 /results/feedback-stats 一致，配置 LLM: {settings.llm_model}）")
    print("=" * 64)
    print(
        f"全部结论 {stats['total_findings']} 条 | 自动确认 {stats['auto_confirmed']}"
        f"（覆盖率 {stats['auto_confirm_rate']}） | 待人工复核 {stats['pending_confirm']}"
    )
    print(
        f"人工复核 {stats['human_reviewed']} 条 | 采纳 {stats['human_confirmed']}"
        f" | 判误报 {stats['human_false_positive']}"
    )
    print(
        f"采纳率 {stats['confirm_rate']} | 人工口径误报率 {stats['false_positive_rate']}"
    )
    for src, bucket in stats["by_source"].items():
        print(f"  {src:>8}: 复核 {bucket['confirmed'] + bucket['false_positive']}"
              f" | 采纳率 {bucket['confirm_rate']}")
    ov = stats["overturn"]
    print(
        f"翻案：事件 {ov['events']} | 翻转 {ov['flips']}"
        f"（纠错自动确认 {ov['auto_corrections']}） | 翻案率 {ov['overturn_rate']}"
    )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n已写入 {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
