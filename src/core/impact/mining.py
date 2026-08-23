"""罚单规则挖掘：从处罚案例违规摘要提取可机检的审查规则候选。

定位约束：LLM 只产出规则草稿（status=draft，不生效），人工在规则库
审核发布后才进入审查引擎；挖掘本身不参与任何风险决策。
关联沉淀：候选规则通过 RuleRegulationLink(source='penalty_mining') 挂到
罚单引用的法规，供后续影响分析按条款反查。
"""

import json
import re

from sqlalchemy.orm import Session

from src.core.llm.client import get_llm
from src.models import PenaltyCase, Rule, RuleRegulationLink
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MINE_SYSTEM = """你是一名金融合规规则工程师。我会给你一条监管处罚案例，
请从其违法违规事实中提取 1-3 条可用正则或关键词在宣传材料里机检的审查规则。

要求：
1. 只提取适合文本匹配的规则（如违规话术、绝对化承诺、误导表述），忽略流程类/资质类违规。
2. domain 只能是 banking/fund/insurance 之一，按受罚业务判断。
3. severity 按罚单严重程度取 high/medium/low。
4. regex 用简洁的中文正则（| 分支），keyword 给 2-6 个词；规则必须能直接命中违规原文。

只输出一个 JSON 数组，不要输出任何其他文字，不要用代码块包裹：
[{"domain": "fund", "rule_name": "禁止xx表述", "rule_type": "regex", "severity": "high",
  "pattern": "保本|稳赚", "description": "依据：罚单认定的xx违规"}]
keyword 类型时用 "keywords": ["词1", "词2"] 代替 pattern。"""

_VALID_DOMAINS = {"banking", "fund", "insurance"}
_VALID_SEVERITY = {"high", "medium", "low"}


def build_mine_messages(case: PenaltyCase) -> list[dict]:
    text = f"案例名称：{case.case_name}\n处罚机构：{case.penalty_org or '未标注'}"
    if case.violation_summary:
        text += f"\n违法违规事实：{case.violation_summary}"
    if case.penalty_result:
        text += f"\n处罚结果：{case.penalty_result}"
    return [
        {"role": "system", "content": _MINE_SYSTEM},
        {"role": "user", "content": text + "\n\n请提取规则候选："},
    ]


def parse_candidates(content: str | None) -> list[dict]:
    """从 LLM 输出解析并校验规则候选，坏条目跳过而不是整体失败。"""
    if not content:
        return []
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match is None:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    candidates = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        rule_type = item.get("rule_type")
        name = str(item.get("rule_name") or "").strip()
        if not name or rule_type not in ("regex", "keyword"):
            continue
        if rule_type == "regex" and not str(item.get("pattern") or "").strip():
            continue
        if rule_type == "keyword" and not [
            k for k in (item.get("keywords") or []) if str(k).strip()
        ]:
            continue
        candidates.append(
            {
                "domain": item.get("domain") if item.get("domain") in _VALID_DOMAINS else "fund",
                "rule_name": name[:128],
                "rule_type": rule_type,
                "severity": (
                    item["severity"] if item.get("severity") in _VALID_SEVERITY else "medium"
                ),
                "pattern": str(item.get("pattern") or "").strip(),
                "keywords": [
                    str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()
                ],
                "description": str(item.get("description") or "")[:512] or None,
            }
        )
    return candidates[:3]


def _to_rule_content(candidate: dict) -> dict:
    if candidate["rule_type"] == "regex":
        condition = {"type": "regex", "pattern": candidate["pattern"]}
    else:
        condition = {"type": "keyword", "keywords": candidate["keywords"], "match_mode": "any"}
    return {"operator": "OR", "conditions": [condition]}


def mine_rule_candidates(
    db: Session, penalty_case_id: int, created_by: int | None = None
) -> list[Rule]:
    """挖掘罚单规则候选：LLM 提取 → 去重 → 落 draft 规则 + 罚单溯源关联。"""
    case = db.get(PenaltyCase, penalty_case_id)
    if case is None:
        raise AppError(ErrorCode.PARAM_ERROR, "处罚案例不存在", http_status=404)

    llm = get_llm()
    if llm is None:
        raise AppError(ErrorCode.PARAM_ERROR, "未配置 LLM API Key，无法挖掘规则候选")
    try:
        content = llm.chat(build_mine_messages(case))
    except Exception:
        logger.exception("罚单 %s 规则挖掘 LLM 调用失败", penalty_case_id)
        raise AppError(ErrorCode.PARAM_ERROR, "规则挖掘 LLM 调用失败，请稍后重试") from None

    candidates = parse_candidates(content)
    if not candidates:
        raise AppError(ErrorCode.PARAM_ERROR, "未能从罚单中提取有效规则候选")

    related_regulation_ids = [int(rid) for rid in (case.related_regulations or [])]
    created: list[Rule] = []
    for candidate in candidates:
        if db.query(Rule).filter(Rule.rule_name == candidate["rule_name"]).count():
            continue  # 同名规则已存在（含上次挖掘），跳过保证幂等
        rule = Rule(
            domain=candidate["domain"],
            rule_name=candidate["rule_name"],
            rule_type=candidate["rule_type"],
            rule_content=_to_rule_content(candidate),
            severity=candidate["severity"],
            description=candidate["description"],
            is_active=0,
            status="draft",
        )
        db.add(rule)
        db.flush()
        if related_regulation_ids:
            db.add(
                RuleRegulationLink(
                    rule_id=rule.id,
                    regulation_id=related_regulation_ids[0],
                    citation=f"罚单：{case.case_name}"[:255],
                    source="penalty_mining",
                    created_by=created_by,
                )
            )
        created.append(rule)
    db.commit()
    logger.info("罚单 %s 挖掘规则候选 %d 条", penalty_case_id, len(created))
    if not created:
        raise AppError(ErrorCode.PARAM_ERROR, "规则候选均已存在（此前已挖掘），无新增")
    return created
