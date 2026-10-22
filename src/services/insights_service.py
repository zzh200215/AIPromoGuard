"""合规洞察：把审查运行数据汇成一屏（纯 SQL 聚合，无 LLM 参与）。

设计取舍：
- 只读聚合，不新增表——数据全部来自 review_tasks / review_results /
  product_materials / review_batches 的既有字段；
- 空数据也要能跑（新装环境首屏给 0，不报错）；
- 口径写死在注释里，避免"这个 76% 到底怎么算的"说不清。

口径：
- 复核采纳率 = confirmed / (confirmed + false_positive)；未复核条目不计入分母
- 整改闭环 = 台账材料 → 检出违规 → 已提交整改版（version != v1）→ 复测 clean
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models import ProductMaterial, Regulation, ReviewBatch, ReviewResult, ReviewTask, Rule


def _by_status(db: Session) -> dict[str, int]:
    return dict(
        db.query(ReviewResult.status, func.count(ReviewResult.id))
        .group_by(ReviewResult.status)
        .all()
    )


def overview(db: Session) -> dict:
    """一屏所需的全部聚合值。"""
    tasks_total = db.query(func.count(ReviewTask.id)).scalar() or 0
    tasks_completed = (
        db.query(func.count(ReviewTask.id)).filter(ReviewTask.status == "completed").scalar() or 0
    )

    findings_total = db.query(func.count(ReviewResult.id)).scalar() or 0
    status_map = _by_status(db)
    confirmed = status_map.get("confirmed", 0)
    pending = status_map.get("pending_confirm", 0)
    false_positive = status_map.get("false_positive", 0)
    reviewed = confirmed + false_positive
    confirm_rate = round(confirmed / reviewed, 3) if reviewed else None
    review_coverage = round(reviewed / findings_total, 3) if findings_total else None

    risk = [
        {"key": key or "unknown", "count": count}
        for key, count in db.query(ReviewResult.risk_level, func.count(ReviewResult.id))
        .group_by(ReviewResult.risk_level)
        .all()
    ]
    sources = [
        {"key": key or "unknown", "count": count}
        for key, count in db.query(ReviewResult.violation_type, func.count(ReviewResult.id))
        .group_by(ReviewResult.violation_type)
        .all()
    ]

    rules_top = [
        {"name": name or "未命名规则", "count": count}
        for name, count in (
            db.query(Rule.rule_name, func.count(ReviewResult.id))
            .join(Rule, Rule.id == ReviewResult.rule_id)
            .group_by(Rule.rule_name)
            .order_by(func.count(ReviewResult.id).desc())
            .limit(8)
            .all()
        )
    ]
    regulations_top = [
        {"name": name or "未关联法规", "count": count}
        for name, count in (
            db.query(Regulation.regulation_name, func.count(ReviewResult.id))
            .join(Regulation, Regulation.id == ReviewResult.regulation_id)
            .group_by(Regulation.regulation_name)
            .order_by(func.count(ReviewResult.id).desc())
            .limit(8)
            .all()
        )
    ]

    # 近 30 天趋势：补零，便于前端直接画折线
    since = date.today() - timedelta(days=29)
    rows = (
        db.query(func.date(ReviewResult.created_at), func.count(ReviewResult.id))
        .filter(ReviewResult.created_at >= datetime.combine(since, datetime.min.time()))
        .group_by(func.date(ReviewResult.created_at))
        .all()
    )
    day_counts = {str(day): count for day, count in rows}
    trend = [
        {
            "date": (since + timedelta(days=offset)).isoformat(),
            "count": day_counts.get((since + timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(30)
    ]

    materials_total = db.query(func.count(ProductMaterial.id)).scalar() or 0
    materials_violation = (
        db.query(func.count(ProductMaterial.id))
        .filter(ProductMaterial.last_review_status == "violation")
        .scalar()
        or 0
    )
    materials_clean = (
        db.query(func.count(ProductMaterial.id))
        .filter(ProductMaterial.last_review_status == "clean")
        .scalar()
        or 0
    )
    materials_remediated = (
        db.query(func.count(ProductMaterial.id))
        .filter(ProductMaterial.version.isnot(None), ProductMaterial.version != "v1")
        .scalar()
        or 0
    )
    material_types = [
        {"name": name or "未分类", "count": count}
        for name, count in db.query(ProductMaterial.material_type, func.count(ProductMaterial.id))
        .group_by(ProductMaterial.material_type)
        .order_by(func.count(ProductMaterial.id).desc())
        .all()
    ]

    batches_total = db.query(func.count(ReviewBatch.id)).scalar() or 0
    batches_completed = (
        db.query(func.count(ReviewBatch.id))
        .filter(ReviewBatch.status == "completed")
        .scalar()
        or 0
    )

    return {
        "cards": {
            "tasks_total": tasks_total,
            "tasks_completed": tasks_completed,
            "findings_total": findings_total,
            "confirmed": confirmed,
            "pending": pending,
            "false_positive": false_positive,
            "confirm_rate": confirm_rate,
            "review_coverage": review_coverage,
            "materials_total": materials_total,
            "materials_violation": materials_violation,
            "materials_clean": materials_clean,
            "batches_total": batches_total,
            "batches_completed": batches_completed,
        },
        "risk": risk,
        "sources": sources,
        "rules_top": rules_top,
        "regulations_top": regulations_top,
        "trend": trend,
        # 复核漏斗：检出 → 已复核 → 采纳（口径 = confirmed）+ 待复核
        "review_funnel": [
            {"label": "检出", "value": findings_total},
            {"label": "已复核", "value": reviewed},
            {"label": "采纳", "value": confirmed},
            {"label": "待复核", "value": pending},
        ],
        # 整改闭环：台账 → 检出违规 → 提交整改版 → clean
        "remediation": {
            "materials_total": materials_total,
            "violation": materials_violation,
            "remediated": materials_remediated,
            "clean": materials_clean,
        },
        "material_types": material_types,
    }
