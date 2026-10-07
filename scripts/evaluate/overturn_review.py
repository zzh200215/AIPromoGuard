"""翻案归因管道（R4-1）：把人工复核翻案项变成飞轮的燃料.

数据流（月度 CLI，非常驻，只读不改）：
  审计留痕（action=result.confirm，detail 含 before_status/verdict）
  → 翻案项（before_status 已是判定结果且被改判；常规复核不计入）
  → 关联 ReviewResult 取原文/规则上下文
  → LLM 辅助归因四分类：rule_missing（规则缺失）/ retrieval_miss（检索
    未召回）/ prompt_mislead（提示词误导）/ parsing_error（解析错误）
  → 月度复盘报告（翻案率趋势、Top 失败模式、各管道去向计数）

设计约束（延续"证据驱动激活"的克制原则）：
- 归因结果**不自动改任何东西**——产出工单式建议（规则缺失→规则挖掘管道、
  prompt 误导→提示词修复+回归集加案例、检索未召回→检索调参、解析错误→
  解析器修复），人工确认后走各管道；
- 无 LLM 时优雅降级：统计报告照常生成，归因列留空（标注"未归因"）；
- 数据卫生：只统计真实人工动作（审计留痕自 2026-08-29 起有明细）。

用法（仓库根目录）:
    python scripts/evaluate/overturn_review.py                    # 上个月
    python scripts/evaluate/overturn_review.py --month 2026-09
    python scripts/evaluate/overturn_review.py --out reports/
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.llm.client import get_llm
from src.infrastructure.database.mysql import SessionLocal
from src.models import AuditLog, ReviewResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

_CATEGORIES = ("rule_missing", "retrieval_miss", "prompt_mislead", "parsing_error")

# 已判定状态（翻案判定的基准，2026-10-05 口径修正）
_JUDGED_STATUSES = {"confirmed", "false_positive"}

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)

_CATEGORY_LABEL = {
    "rule_missing": "规则缺失 → 规则挖掘管道（mine_rules + 对抗门禁）",
    "retrieval_miss": "检索未召回 → 检索调参（RRF 权重/chunk 策略）",
    "prompt_mislead": "提示词误导 → 提示词修复 + 回归集加案例",
    "parsing_error": "解析错误 → 解析器修复 + 加测试文档",
}

_ATTRIBUTION_SYSTEM = (
    "你是合规审查系统的质量分析员。给定一条被人工复核推翻（翻案）的审查结论："
    "原文片段、系统当时的判定、以及判定所依据的规则/检索上下文摘要，"
    "判断翻案最可能的根因（单选）：\n"
    "- rule_missing：规则库确实缺这类违规的模式（误报源于规则设计，而非匹配错误）\n"
    "- retrieval_miss：相关的法规条款没有被检索召回，导致判断缺少依据\n"
    "- prompt_mislead：检索到了依据但提示词引导了错误判断（如把正常披露当违规）\n"
    "- parsing_error：文档解析/文本抽取本身出错（原文片段残缺或乱序导致误判）\n"
    '只输出 JSON：{"category": "rule_missing|retrieval_miss|prompt_mislead|parsing_error", '
    '"evidence": "一句话依据"}'
)


def _is_overturn(before, verdict) -> bool:
    """翻案判定（唯一定义点，与 src/services/result_trail.py 同口径）：
    before 必须已是判定结果（confirmed/false_positive）且被改成另一个判定。
    常规复核（pending_confirm → confirmed/false_positive）不算翻案。"""
    return before in _JUDGED_STATUSES and verdict is not None and before != verdict


def _fetch_overturns(db, month_first, month_next):
    """审计留痕中的**翻案**项（改判既有结论），含关联结论上下文。

    口径（2026-10-05 修正）：翻案 = before_status 已是判定结果
    （confirmed/false_positive）且被改成另一个判定。此前用 before != verdict
    判定，会把常规复核（pending_confirm → confirmed）误计为翻案，翻案率虚高
    ——状态与判定是两个命名空间，不能直接比较。

    month_first/month_next 为 None 时跳过时间过滤（测试与手工排查用）。
    """
    query = db.query(AuditLog).filter(AuditLog.action == "result.confirm")
    if month_first is not None:
        query = query.filter(AuditLog.created_at >= month_first)
    if month_next is not None:
        query = query.filter(AuditLog.created_at < month_next)
    rows = query.order_by(AuditLog.id).all()
    overturns = []
    for log in rows:
        if not log.detail:
            continue
        try:
            detail = json.loads(log.detail)
        except json.JSONDecodeError:
            continue
        before = detail.get("before_status")
        verdict = detail.get("verdict")
        if not _is_overturn(before, verdict):
            continue
        result = db.get(ReviewResult, int(log.resource_id)) if log.resource_id else None
        overturns.append(
            {
                "log_id": log.id,
                "at": log.created_at.isoformat(timespec="seconds") if log.created_at else "",
                "reviewer": log.username,
                "before_status": before,
                "before_auto_confirmed": bool(detail.get("before_auto_confirmed")),
                "verdict": verdict,
                "result_id": log.resource_id,
                "original_text": (result.original_text if result else "")[:200],
                "description": (result.description if result else "")[:200],
                "violation_type": result.violation_type if result else "",
                "risk_level": result.risk_level if result else "",
            }
        )
    return overturns


def _fetch_stats(db, month_first, month_next):
    """复核漏斗：人工复核总数、翻案数、纠错自动确认子集。"""
    query = db.query(AuditLog).filter(AuditLog.action == "result.confirm")
    if month_first is not None:
        query = query.filter(AuditLog.created_at >= month_first)
    if month_next is not None:
        query = query.filter(AuditLog.created_at < month_next)
    rows = query.all()
    total = flipped = auto_flipped = 0
    for log in rows:
        if not log.detail:
            continue
        try:
            d = json.loads(log.detail)
        except json.JSONDecodeError:
            continue
        before, verdict = d.get("before_status"), d.get("verdict")
        if not before or not verdict:
            continue
        total += 1
        if _is_overturn(before, verdict):
            flipped += 1
            if d.get("before_auto_confirmed"):
                auto_flipped += 1
    return {"human_actions": total, "overturns": flipped, "auto_confirm_overturns": auto_flipped}


def _attribute(llm, item: dict) -> dict:
    """单条翻案的 LLM 归因（失败返回未归因，不阻断批次）。"""
    prompt = (
        f"原文片段：{item['original_text'][:300]}\n"
        f"系统当时判定：{item['before_status']}（{item['violation_type']}，"
        f"{item['risk_level']}风险）\n"
        f"判定说明：{item['description'][:200]}\n"
        f"人工复核改判为：{item['verdict']}"
    )
    try:
        result = llm.complete(
            [
                {"role": "system", "content": _ATTRIBUTION_SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
        content = getattr(result, "content", "") or ""
        m = _JSON_OBJECT_RE.search(content)
        data = json.loads(m.group()) if m else {}
        cat = data.get("category")
        if cat in _CATEGORIES:
            return {"category": cat, "evidence": str(data.get("evidence") or "")[:150]}
    except Exception as exc:  # noqa: BLE001 — 单条失败不阻断
        logger.warning("归因失败（标记未归因）: %s", exc)
    return {"category": "unattributed", "evidence": "LLM 归因失败"}


def build_report(month: str, limit: int, use_llm: bool) -> dict:
    month_first = date.fromisoformat(month + "-01")
    if month_first.month == 12:
        month_next = date(month_first.year + 1, 1, 1)
    else:
        month_next = date(month_first.year, month_first.month + 1, 1)

    db = SessionLocal()
    try:
        stats = _fetch_stats(db, month_first, month_next)
        overturns = _fetch_overturns(db, month_first, month_next)
        if limit:
            overturns = overturns[:limit]
    finally:
        db.close()

    llm = get_llm() if use_llm else None
    if llm is None:
        print("LLM 未配置：生成统计报告，归因列留空（未归因）")
    for item in overturns:
        item["attribution"] = _attribute(llm, item) if llm else {
            "category": "unattributed", "evidence": "未启用 LLM 归因"
        }

    cat_counts = Counter(o["attribution"]["category"] for o in overturns)
    pipeline = Counter(
        _CATEGORY_LABEL.get(o["attribution"]["category"], "未归因（人工确认后分派）")
        for o in overturns
    )
    report = {
        "month": month,
        "stats": stats,
        "overturn_rate": (
            round(stats["overturns"] / stats["human_actions"], 3)
            if stats["human_actions"]
            else None
        ),
        "category_counts": dict(cat_counts),
        "pipeline_suggestions": dict(pipeline),
        "overturns": overturns,
        "note": "归因建议为工单式产出，人工确认后走各管道；本脚本不自动修改任何规则/提示词",
    }
    return report


def main() -> int:
    import datetime as _dt

    parser = argparse.ArgumentParser(description="翻案归因月度复盘（只读，工单式产出）")
    today = date.today()
    last_day_prev = date(today.year, today.month, 1) - _dt.timedelta(days=1)
    default_month = last_day_prev.strftime("%Y-%m")
    parser.add_argument("--month", default=default_month, help="复盘月份 YYYY-MM（默认上个月）")
    parser.add_argument("--limit", type=int, default=0, help="最多归因 N 条（0=全部）")
    parser.add_argument(
        "--out", default=None, help="报告输出目录（默认 scripts/evaluate/reports/）"
    )
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 归因，只出统计")
    args = parser.parse_args()

    report = build_report(args.month, args.limit, use_llm=not args.no_llm)

    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"overturn_{args.month}.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n== 翻案复盘 {args.month} ==\n"
        f"人工复核 {report['stats']['human_actions']} 次，翻案 {report['stats']['overturns']}"
        f"（纠错自动确认 {report['stats']['auto_confirm_overturns']}）\n"
        f"翻案率 {report['overturn_rate']}\n"
        f"失败模式分布：{report['category_counts']}\n"
        f"管道去向：{report['pipeline_suggestions']}\n"
        f"明细：{out_json}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
