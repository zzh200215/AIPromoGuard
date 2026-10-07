"""半自动规则精调（方向③）：基于人工复核统计，对高误报规则生成建议动作并应用。

- build_rule_suggestions：按规则聚合人工复核结果（confirmed_by>0，口径同 rules/quality），
  对"复核样本 ≥ min_samples 且误报率 ≥ fp_threshold"的规则生成建议：
  - deactivate：纯误报（confirmed==0 且 fp_rate ≥ 0.9）→ 建议停用；
  - remove_keyword：keyword 条件某词在 ≥ keyword_fp_min 次误报中命中、从未被确认
    → 建议从该条件 keywords 中移除（收紧过宽关键词）；
  - set_threshold：确认与误报在置信度分布上可分离（max_fp < min_confirmed）→ 建议抬
    该规则阈值（写入 rule_content.min_confidence，只影响本规则，不动全局 min_confidence）。
  建议实时计算、不落库（管理员不点应用即视为忽略）。
- apply_suggestion：应用建议直接改 rule.is_active / rule_content（version+1），无迁移。
"""

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.models import ReviewResult, Rule
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

_VALID_ACTIONS = {"deactivate", "remove_keyword", "set_threshold"}


def _tuning_cfg() -> dict:
    return settings.app_config("rule_engine").get("tuning", {})


def _keyword_conditions(rule_content: dict) -> list[tuple[int, dict]]:
    """返回 (condition_index, condition)，仅 keyword 类型条件。"""
    conditions = rule_content.get("conditions") or []
    return [(i, c) for i, c in enumerate(conditions) if c.get("type") == "keyword"]


def _review_counts(db: Session) -> dict[int, dict[str, int]]:
    """按 rule_id 聚合人工复核统计（口径同 rules/quality，confirmed_by>0）。"""
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
    return acc


def _texts_of(db: Session, rule_id: int, status: str) -> list[str]:
    rows = (
        db.query(ReviewResult.original_text)
        .filter(ReviewResult.rule_id == rule_id, ReviewResult.status == status)
        .all()
    )
    return [r[0] for r in rows]


def _hit_count(texts: list[str], keyword: str) -> int:
    return sum(1 for t in texts if keyword in (t or ""))


def _confidences_of(db: Session, rule_id: int, status: str) -> list[float]:
    """该规则某状态（confirmed/false_positive）下每条复核的置信度（供阈值校准）。"""
    rows = (
        db.query(ReviewResult.confidence_score)
        .filter(ReviewResult.rule_id == rule_id, ReviewResult.status == status)
        .all()
    )
    return [float(r[0]) for r in rows if r[0] is not None]


def compute_threshold_suggestion(
    confirmed_confs: list[float], fp_confs: list[float]
) -> tuple[float, bool] | None:
    """从置信度分布求可分离阈值：返回 (阈值, 是否干净分隔)。

    规则置信度目前由 matcher 固生生（regex 0.95 / keyword 0.85），只有
    确认/误报的置信度分布存在空隙（max_fp < min_confirmed）时，抬阈值才有
    意义——能全保确认、全滤误报。无空隙则返回 None（建议交由 heuristics
    如停用/移除关键词处理，而不是盲目抬阈值）。
    """
    if not fp_confs:
        return None
    max_fp = max(fp_confs)
    if confirmed_confs:
        min_conf = min(confirmed_confs)
        if max_fp < min_conf:
            threshold = round((max_fp + min_conf) / 2, 2)
            return (min(max(threshold, 0.5), 0.95), True)
    return None


def _build_suggestion(
    rule: Rule,
    bucket: dict[str, int],
    fp_rate: float,
    action: str,
    keyword: str | None,
    condition_index: int | None,
    reason: str,
    fp_samples: list[str],
    threshold: float | None = None,
) -> dict:
    return {
        "rule_id": rule.id,
        "rule_name": rule.rule_name,
        "domain": rule.domain,
        "severity": rule.severity,
        "action": action,
        "keyword": keyword,
        "condition_index": condition_index,
        "reason": reason,
        "confirmed": bucket.get("confirmed", 0),
        "false_positive": bucket.get("false_positive", 0),
        "fp_rate": round(fp_rate, 3),
        "fp_samples": fp_samples,
        **({"threshold": threshold} if threshold is not None else {}),
    }


def build_rule_suggestions(db: Session) -> list[dict]:
    """生成规则精调建议列表（按误报率降序）。"""
    cfg = _tuning_cfg()
    min_samples = int(cfg.get("min_samples", 3))
    fp_threshold = float(cfg.get("fp_threshold", 0.5))
    keyword_fp_min = int(cfg.get("keyword_fp_min", 2))

    suggestions: list[dict] = []
    for rule_id, bucket in _review_counts(db).items():
        reviewed = bucket.get("confirmed", 0) + bucket.get("false_positive", 0)
        if reviewed < min_samples:
            continue
        fp = bucket.get("false_positive", 0)
        fp_rate = fp / reviewed
        if fp_rate < fp_threshold:
            continue

        rule = db.get(Rule, rule_id)
        if rule is None or rule.is_active != 1:
            continue
        fp_texts = _texts_of(db, rule_id, "false_positive")

        # 动作分级：纯误报 → 停用；否则尝试移除误报关键词
        if bucket.get("confirmed", 0) == 0 and fp_rate >= 0.9:
            suggestions.append(
                _build_suggestion(
                    rule, bucket, fp_rate, "deactivate", None, None,
                    f"纯误报（{fp} 次误报 / 0 次确认，误报率 {fp_rate:.0%}），建议停用规则",
                    fp_texts[:3],
                )
            )
            continue

        conf_texts = _texts_of(db, rule_id, "confirmed")
        best: tuple[int, str, int] | None = None  # (fp_hits, keyword, condition_index)
        for idx, cond in _keyword_conditions(rule.rule_content or {}):
            for kw in cond.get("keywords") or []:
                fp_hits = _hit_count(fp_texts, kw)
                if fp_hits >= keyword_fp_min and _hit_count(conf_texts, kw) == 0:
                    if best is None or fp_hits > best[0]:
                        best = (fp_hits, kw, idx)
        if best is not None:
            fp_hits, kw, idx = best
            suggestions.append(
                _build_suggestion(
                    rule, bucket, fp_rate, "remove_keyword", kw, idx,
                    f"关键词「{kw}」在 {fp_hits} 次误报中命中、从未被确认，建议从关键词中移除",
                    fp_texts[:3],
                )
            )
            continue

        # 无关键词可移除 → 尝试「调阈值」杠杆：确认/误报置信度分布可分离时抬本规则阈值
        confirmed_confs = _confidences_of(db, rule_id, "confirmed")
        fp_confs = _confidences_of(db, rule_id, "false_positive")
        thr = compute_threshold_suggestion(confirmed_confs, fp_confs)
        if thr is not None:
            threshold, separating = thr
            max_fp = max(fp_confs)
            min_conf = min(confirmed_confs) if confirmed_confs else None
            tail = "（可全保确认、全滤误报）" if separating else "（近似分隔，请人工确认）"
            suggestions.append(
                _build_suggestion(
                    rule, bucket, fp_rate, "set_threshold", None, None,
                    f"确认置信度≥{min_conf} / 误报置信度≤{max_fp}，可调阈值 {threshold} 分隔"
                    f"{tail}；只影响本规则，不动全局 min_confidence",
                    fp_texts[:3],
                    threshold,
                )
            )
            continue

    suggestions.sort(key=lambda s: s["fp_rate"], reverse=True)
    return suggestions


def apply_suggestion(
    db: Session,
    rule_id: int,
    action: str,
    condition_index: int | None = None,
    keyword: str | None = None,
    threshold: float | None = None,
) -> Rule:
    """应用精调建议：deactivate 停用；remove_keyword 移词；set_threshold 抬该规则阈值。
    version+1。
    """
    if action not in _VALID_ACTIONS:
        raise AppError(ErrorCode.PARAM_ERROR, f"不支持的 action: {action}")
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise AppError(ErrorCode.PARAM_ERROR, "规则不存在", http_status=404)

    if action == "deactivate":
        rule.is_active = 0
    elif action == "set_threshold":
        if threshold is None:
            raise AppError(ErrorCode.PARAM_ERROR, "set_threshold 需要 threshold")
        if not (0.5 <= threshold <= 0.95):
            raise AppError(ErrorCode.PARAM_ERROR, "threshold 需在 [0.5, 0.95]")
        content = dict(rule.rule_content or {})
        content["min_confidence"] = threshold
        rule.rule_content = content
        flag_modified(rule, "rule_content")
    else:
        if condition_index is None or not keyword:
            raise AppError(ErrorCode.PARAM_ERROR, "remove_keyword 需要 condition_index 与 keyword")
        content = dict(rule.rule_content or {})
        conditions = list(content.get("conditions") or [])
        if not (0 <= condition_index < len(conditions)):
            raise AppError(ErrorCode.PARAM_ERROR, "condition_index 越界")
        cond = dict(conditions[condition_index])
        if cond.get("type") != "keyword":
            raise AppError(ErrorCode.PARAM_ERROR, "仅 keyword 条件支持移除关键词")
        kws = list(cond.get("keywords") or [])
        if keyword not in kws:
            raise AppError(ErrorCode.PARAM_ERROR, f"关键词「{keyword}」不在规则中")
        kws.remove(keyword)
        cond["keywords"] = kws
        conditions[condition_index] = cond
        content["conditions"] = conditions
        # JSON 列原地 mutate 不触发 UPDATE，需显式标记
        rule.rule_content = content
        flag_modified(rule, "rule_content")

    rule.version += 1
    db.commit()
    db.refresh(rule)
    logger.info("规则 %s(%s) 应用精调建议 %s", rule.rule_name, rule_id, action)
    return rule
