"""报告与人工复核结论同步。

报告 JSON 在审查图终点生成一次；此后的确认/翻案（POST /results/{id}/confirm）只改
review_results 表。合规留档要求导出的 md/pdf 与最终结论一致，因此读取/下载时对比
results 的最新 confirmed_at 与报告内记录，过期则按 DB 现状重算并回写落盘文件。

报告 violations 与 review_results 同序同源（_persist_results 按同一 findings 列表
顺序落库），按下标对齐补充人工结论与结构化法规引用。
"""

import json
from collections import Counter
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.report.markdown import render_markdown
from src.models import Regulation, ReviewResult, ReviewTask, TaskSignOff
from src.utils.logger import get_logger

logger = get_logger(__name__)


def merge_human_decisions(db: Session, report: dict, task_id: int) -> dict:
    """把 review_results 的人工判定合并进报告数据（原地修改并返回）。

    - 逐条违规附 human_status / human_confirmed_by / 结构化法规引用；
    - 汇总 human_review 块：自动确认、人工复核数、剔除误报后的最终违规计数；
    - regulations：任务引用的法规（id/名称/文号），供前端与报告可点跳转。
    """
    results = (
        db.query(ReviewResult)
        .filter(ReviewResult.task_id == task_id)
        .order_by(ReviewResult.id.asc())
        .all()
    )
    violations = report.get("violations") or []
    if len(results) == len(violations):
        for v, r in zip(violations, results, strict=False):
            v["result_id"] = r.id
            v["human_status"] = r.status
            v["human_confirmed_by"] = r.confirmed_by
            # 系统自动确认由 status + 无 actor 派生（PR-7：不再用哨兵 0）
            v["human_auto_confirmed"] = r.auto_confirmed
            v["human_confirmed_at"] = r.confirmed_at.isoformat() if r.confirmed_at else None
            if r.regulation_id:
                v["regulation_id"] = r.regulation_id
            if r.article_id:
                v["article_id"] = r.article_id

    counts = Counter(r.status for r in results)
    last_confirmed_at = max(
        (r.confirmed_at for r in results if r.confirmed_at is not None), default=None
    )
    final_counter = Counter(r.risk_level for r in results if r.status != "false_positive")
    report["human_review"] = {
        "pending_confirm": counts.get("pending_confirm", 0),
        "confirmed": counts.get("confirmed", 0),
        "false_positive": counts.get("false_positive", 0),
        # 系统自动确认（status=confirmed 且无人工 actor；PR-7 起以 NULL 表达），不计人工复核
        "auto_confirmed": sum(1 for r in results if r.auto_confirmed),
        "manual_reviewed": sum(
            1 for r in results if r.status in ("confirmed", "false_positive") and r.confirmed_by
        ),
        "final_total": sum(1 for r in results if r.status != "false_positive"),
        "final_high": final_counter.get("high", 0),
        "final_medium": final_counter.get("medium", 0),
        "final_low": final_counter.get("low", 0),
        "last_confirmed_at": last_confirmed_at.isoformat() if last_confirmed_at else None,
    }

    reg_ids = {r.regulation_id for r in results if r.regulation_id}
    if reg_ids:
        regs = db.query(Regulation).filter(Regulation.id.in_(reg_ids)).all()
        report["regulations"] = [
            {
                "id": g.id,
                "regulation_name": g.regulation_name,
                "regulation_no": g.regulation_no,
            }
            for g in regs
        ]
    return report


def merge_sign_off(db: Session, report: dict, task_id: int) -> dict:
    """把最新一次审核签发合并进报告数据（原地修改并返回）。

    签发/改签不触发报告重算，只在此处实时对齐 DB；无签发记录时为 None。
    """
    rec = (
        db.query(TaskSignOff)
        .filter(TaskSignOff.task_id == task_id)
        .order_by(TaskSignOff.id.desc())
        .first()
    )
    report["sign_off"] = (
        {
            "decision": rec.decision,
            "username": rec.username,
            "note": rec.note,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        }
        if rec
        else None
    )
    return report


def _is_stale(report: dict, latest_confirmed_at, latest_sign_off_at=None) -> bool:
    """报告内记录的结论/签发时间与 DB 最新记录不一致即视为过期。"""
    stored = (report.get("human_review") or {}).get("last_confirmed_at")
    if "human_review" not in report:
        return True
    latest = latest_confirmed_at.isoformat() if latest_confirmed_at is not None else None
    if stored != latest:
        return True
    stored_sign_off = report.get("sign_off")
    stored_sign_at = stored_sign_off.get("created_at") if stored_sign_off else None
    latest_sign = latest_sign_off_at.isoformat() if latest_sign_off_at is not None else None
    return stored_sign_at != latest_sign


def refresh_report(db: Session, task: ReviewTask) -> dict:
    """读取任务报告并同步人工结论/签发状态；过期则重算并回写 json + md。

    调用方需先确认任务 completed 且 report_path 落盘存在。
    """
    path = Path(task.report_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    latest = (
        db.query(func.max(ReviewResult.confirmed_at))
        .filter(ReviewResult.task_id == task.id)
        .scalar()
    )
    latest_sign_off = (
        db.query(func.max(TaskSignOff.created_at))
        .filter(TaskSignOff.task_id == task.id)
        .scalar()
    )
    if _is_stale(report, latest, latest_sign_off):
        report = merge_human_decisions(db, report, task.id)
        merge_sign_off(db, report, task.id)
        # 结论变化后 AI 综述不再代表当前状态：标记过期，下次访问由 review_copilot 重算
        if isinstance(report.get("ai_summary"), dict):
            report["ai_summary"]["stale"] = True
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
        logger.info("报告已按最新人工结论刷新: task_id=%s", task.id)
        return report
    # 未过期也实时合并签发状态：签发/改签不落盘重算，但读取与导出必须最新
    return merge_sign_off(db, report, task.id)
