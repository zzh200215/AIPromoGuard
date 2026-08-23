"""法规影响分析：监管事件 → 受影响规则 → 存量材料 → 罚单佐证 → 风险排序 → 复审建议。

对外唯一入口 analyze()，结果落 ImpactAssessment（明细存 items JSON）。

设计约定：
- 风险排序是确定性公式：材料预扫命中规则的严重度权重(1-3) + 违规历史(+2)
  + 罚单佐证(+1，仅对预扫命中的材料)，LLM 不参与风险决策；
  需要解释文案时在 API 层另行生成。
- 预扫复用规则引擎（rule_scanner）对可定位的 txt 材料文档真实匹配，
  无法定位文档的材料回退域级规则严重度（保守估算）。
- 定位阶段各一个函数，打分与分词是纯函数，可独立单测。
- 一个监管事件只保留一份评估：重复 analyze 覆盖 draft 的 items；
  已进入人工流程（pending_review/confirmed）则原样返回，不覆盖人工数据。
"""

import re
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.rule_engine import rule_scanner
from src.models import (
    Article,
    ImpactAssessment,
    PenaltyCase,
    ProductMaterial,
    RegulationUpdate,
    Rule,
    RuleRegulationLink,
)
from src.parsers.base import TextBlock
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 规则领域 → 材料产品类型（银行理财归入 banking 域）
_DOMAIN_TO_PRODUCT = {"fund": "fund", "insurance": "insurance", "banking": "wealth"}
_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}

_KEYWORD_FALLBACK_MIN_OVERLAP = 2  # 关键词兜底命中的最小二元组重叠数
_PENALTY_EVIDENCE_CAP = 5

_STOP_CHARS = set("的了和与及或者在是有对为中上等其本并予以进行有关加强进一步")
_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{8}$")


def _text_bigrams(text: str) -> set[str]:
    """中文文本二元组集合（停用字过滤），用于规则与监管事件的确定性关键词匹配。"""
    grams: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        for i in range(len(run) - 1):
            gram = run[i : i + 2]
            if gram[0] not in _STOP_CHARS and gram[1] not in _STOP_CHARS:
                grams.add(gram)
    return grams


def _score_material(
    max_severity: str | None, last_review_status: str | None, penalty_count: int
) -> tuple[int, str]:
    """确定性打分：severity 权重 + 违规历史 + 罚单佐证；>=4 high，>=2 medium，否则 low。"""
    weight = _SEVERITY_WEIGHT.get(max_severity or "", 1)
    history = 2 if last_review_status == "violation" else 0
    evidence = 1 if penalty_count > 0 else 0
    score = weight + history + evidence
    level = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return score, level


def _locate_rules(
    db: Session, regulation_ids: list[int], event_text: str, domain: str | None
) -> tuple[list[Rule], dict[int, str]]:
    """受影响规则：优先 RuleRegulationLink 结构化关联，未关联的在同域规则里做关键词兜底。

    event_text 为事件文本（法规标题+摘要或罚单名称+违规摘要），domain 为空时兜底全域。
    """
    matched_by: dict[int, str] = {}
    rules: list[Rule] = []

    linked_rule_ids: set[int] = set()
    if regulation_ids:
        article_ids = [
            row[0]
            for row in db.query(Article.id)
            .filter(Article.regulation_id.in_(regulation_ids))
            .all()
        ]
        link_q = db.query(RuleRegulationLink).filter(
            RuleRegulationLink.regulation_id.in_(regulation_ids)
        )
        if article_ids:
            link_q = link_q.filter(
                or_(
                    RuleRegulationLink.regulation_id.in_(regulation_ids),
                    RuleRegulationLink.article_id.in_(article_ids),
                )
            )
        linked_rule_ids = {link.rule_id for link in link_q.all()}

    if linked_rule_ids:
        rules = (
            db.query(Rule)
            .filter(Rule.id.in_(linked_rule_ids), Rule.is_active == 1)
            .all()
        )
        matched_by = {rule.id: "link" for rule in rules}

    event_grams = _text_bigrams(event_text)
    if event_grams:
        candidate_q = db.query(Rule).filter(Rule.is_active == 1)
        if domain:
            candidate_q = candidate_q.filter(Rule.domain == domain)
        for rule in candidate_q.all():
            if rule.id in linked_rule_ids:
                continue
            overlap = event_grams & _text_bigrams(
                f"{rule.rule_name} {rule.description or ''}"
            )
            if len(overlap) >= _KEYWORD_FALLBACK_MIN_OVERLAP:
                rules.append(rule)
                matched_by[rule.id] = "keyword"
    return rules, matched_by


def _locate_materials(db: Session, rules: list[Rule]) -> list[ProductMaterial]:
    """受影响存量材料：命中规则所属领域对应的在用产品类型全部材料。"""
    products = {
        _DOMAIN_TO_PRODUCT[rule.domain]
        for rule in rules
        if rule.domain in _DOMAIN_TO_PRODUCT
    }
    if not products:
        return []
    return (
        db.query(ProductMaterial)
        .filter(ProductMaterial.status == "active", ProductMaterial.product_type.in_(products))
        .all()
    )


def _locate_penalties(db: Session, regulation_ids: list[int]) -> list[PenaltyCase]:
    """罚单佐证：关联法规与本事件匹配库内法规相交的处罚案例（库容小，全量过滤）。"""
    if not regulation_ids:
        return []
    rid_set = set(regulation_ids)
    cases = db.query(PenaltyCase).all()
    return [
        case
        for case in cases
        if rid_set & {int(rid) for rid in (case.related_regulations or [])}
    ][:_PENALTY_EVIDENCE_CAP]


def material_document_path(document_id: str | None) -> Path | None:
    """台账 document_id → 已上传文档路径（doc_xxxxxxxx 白名单 + upload_dir 单层定位）。"""
    if not document_id or not _DOC_ID_RE.match(document_id):
        return None
    matches = list(Path(settings.upload_dir).glob(f"*/{document_id}.*"))
    return matches[0] if matches else None


def _preview_rule_hits(
    rules: list[Rule], materials: list[ProductMaterial]
) -> tuple[set[int], dict[int, set[int]]]:
    """对可定位的 txt 材料文档跑规则引擎预扫。

    返回（已预扫的材料 id 集合, 材料id → 命中规则id 集合）；
    无文档/非 txt/读取失败的材料不在 scanned 中，打分回退域级保守估算。
    """
    scanned: set[int] = set()
    hits: dict[int, set[int]] = {}
    for material in materials:
        path = material_document_path(material.document_id)
        if path is None or path.suffix.lower() != ".txt":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("材料 %s 文档 %s 读取失败，跳过预扫", material.id, path)
            continue
        scanned.add(material.id)
        rule_hits = rule_scanner.scan([TextBlock(text=text)], rules)
        hits[material.id] = {int(h.rule_id) for h in rule_hits}
    return scanned, hits


def _build_items(
    rules: list[Rule],
    matched_by: dict[int, str],
    materials: list[ProductMaterial],
    penalties: list[PenaltyCase],
    preview: tuple[set[int], dict[int, set[int]]],
) -> tuple[dict, tuple[int, int, int]]:
    scanned, hit_map = preview
    rule_items = [
        {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "domain": rule.domain,
            "severity": rule.severity,
            "matched_by": matched_by.get(rule.id, "keyword"),
            "confirm_status": "pending",
        }
        for rule in rules
    ]

    material_items = []
    for material in materials:
        m_rules = [
            r for r in rules if _DOMAIN_TO_PRODUCT.get(r.domain) == material.product_type
        ]
        hit_rules = [r for r in m_rules if r.id in hit_map.get(material.id, set())]
        if material.id in scanned:
            # 预扫命中决定严重度；罚单佐证只加给有命中的材料
            max_severity = max((r.severity for r in hit_rules), default="low")
            penalty_evidence = len(penalties) if hit_rules else 0
            reason = f"规则预扫命中{len(hit_rules)}条（最高{max_severity}风险）"
        else:
            # 无可读文档：回退域级规则严重度，保守计入罚单佐证
            max_severity = max((r.severity for r in m_rules), default="low")
            penalty_evidence = len(penalties)
            reason = f"命中规则{len(m_rules)}条（最高{max_severity}风险）"
        if material.last_review_status == "violation":
            reason += "；历史审查存在违规"
        if penalty_evidence:
            reason += f"；关联罚单{penalty_evidence}件"
        score, level = _score_material(
            max_severity, material.last_review_status, penalty_evidence
        )
        material_items.append(
            {
                "material_id": material.id,
                "name": material.name,
                "product_type": material.product_type,
                "material_type": material.material_type,
                "owner": material.owner,
                "document_id": material.document_id,
                "last_review_status": material.last_review_status,
                "matched_rules": [r.id for r in m_rules],
                "hit_rules": [r.id for r in hit_rules],
                "risk_score": score,
                "risk_level": level,
                "reason": reason,
                "evidence_penalty_case_ids": [c.id for c in penalties],
                "confirm_status": "pending",
            }
        )
    material_items.sort(key=lambda item: (-item["risk_score"], item["name"]))

    counts = tuple(
        sum(1 for item in material_items if item["risk_level"] == level)
        for level in ("high", "medium", "low")
    )
    items = {"rules": rule_items, "materials": material_items}
    return items, counts


def _build_summary(
    regulation_ids: list[int],
    rules: list[Rule],
    materials: list[ProductMaterial],
    penalties: list[PenaltyCase],
    counts: tuple[int, int, int],
) -> str:
    high, medium, low = counts
    parts = [
        f"关联法规{len(regulation_ids)}部",
        f"命中规则{len(rules)}条",
        f"受影响材料{len(materials)}份（高{high}/中{medium}/低{low}）",
        f"佐证罚单{len(penalties)}件",
    ]
    if high + medium > 0:
        parts.append(f"建议对{high + medium}份高/中风险材料发起批量复审")
    return "，".join(parts) + "。"


def analyze(
    db: Session,
    regulation_update_id: int | None = None,
    penalty_case_id: int | None = None,
    created_by: int | None = None,
) -> ImpactAssessment:
    """对一个监管事件（新规或处罚案例）执行影响分析并落库，返回评估记录。

    regulation_update_id 与 penalty_case_id 二选一。同一事件只保留一份评估：
    draft 状态重复分析覆盖 items；pending_review/confirmed 状态原样返回
    （人工数据不覆盖）。
    """
    if (regulation_update_id is None) == (penalty_case_id is None):
        raise AppError(ErrorCode.PARAM_ERROR, "regulation_update_id 与 penalty_case_id 必须二选一")

    if regulation_update_id is not None:
        upd = db.get(RegulationUpdate, regulation_update_id)
        if upd is None:
            raise AppError(ErrorCode.REGULATION_UPDATE_NOT_FOUND)
        regulation_ids = [
            int(m["regulation_id"])
            for m in (upd.matched_regulations or [])
            if m.get("regulation_id") is not None
        ]
        event_text = f"{upd.title} {upd.llm_summary or ''}"
        domain, title = upd.domain, f"影响评估：{upd.title}"
        existing = (
            db.query(ImpactAssessment)
            .filter(ImpactAssessment.regulation_update_id == regulation_update_id)
            .one_or_none()
        )
    else:
        case = db.get(PenaltyCase, penalty_case_id)
        if case is None:
            raise AppError(ErrorCode.PARAM_ERROR, "处罚案例不存在", http_status=404)
        regulation_ids = [int(rid) for rid in (case.related_regulations or [])]
        event_text = f"{case.case_name} {case.violation_summary or ''}"
        domain, title = None, f"影响评估：{case.case_name}"  # 罚单不定域，兜底全域
        existing = (
            db.query(ImpactAssessment)
            .filter(ImpactAssessment.penalty_case_id == penalty_case_id)
            .one_or_none()
        )

    if existing is not None and existing.status != "draft":
        logger.info("影响评估 %s 状态 %s，跳过重复分析", existing.id, existing.status)
        return existing

    rules, matched_by = _locate_rules(db, regulation_ids, event_text, domain)
    materials = _locate_materials(db, rules)
    penalties = _locate_penalties(db, regulation_ids)
    preview = _preview_rule_hits(rules, materials)
    items, counts = _build_items(rules, matched_by, materials, penalties, preview)
    summary = _build_summary(regulation_ids, rules, materials, penalties, counts)

    if existing is None:
        assessment = ImpactAssessment(
            regulation_update_id=regulation_update_id,
            penalty_case_id=penalty_case_id,
            title=title[:255],
            status="draft",
            created_by=created_by,
        )
        db.add(assessment)
    else:
        assessment = existing
    assessment.items = items
    assessment.high_count, assessment.medium_count, assessment.low_count = counts
    assessment.summary = summary[:1024]
    db.commit()
    db.refresh(assessment)
    logger.info(
        "影响分析完成 update=%s penalty=%s 规则%d 材料%d 罚单%d",
        regulation_update_id, penalty_case_id, len(rules), len(materials), len(penalties),
    )
    return assessment
