"""RuleScanner 节点：加载 active 规则，按领域对文档块执行规则扫描。

W18：按 app.yaml rule_engine.min_confidence 过滤低置信命中，降低误报。
"""

from dataclasses import asdict

from src.core.agents.state import ReviewState
from src.core.rule_engine import RuleHit, rule_scanner
from src.infrastructure.database.mysql import SessionLocal
from src.models import Rule
from src.parsers.base import TextBlock
from src.utils.config import settings


def _hit_to_dict(hit: RuleHit) -> dict:
    data = asdict(hit)
    data["related_regulations"] = list(data.get("related_regulations") or [])
    return data


def rule_scan(state: ReviewState) -> dict:
    db = SessionLocal()
    try:
        rules = db.query(Rule).filter(Rule.is_active == 1).all()
    finally:
        db.close()

    blocks = [
        TextBlock(
            text=b["text"],
            page=b.get("page"),
            paragraph=b.get("paragraph"),
            heading=b.get("heading", False),
        )
        for b in state.get("blocks", [])
    ]
    hits = rule_scanner.scan(blocks, rules, domain=state.get("domain"))

    # W18：过滤低于置信度阈值的命中（app.yaml rule_engine.min_confidence）
    min_conf = settings.app_config("rule_engine").get("min_confidence", 0.5)
    if min_conf > 0:
        hits = [h for h in hits if h.confidence >= min_conf]

    return {"rule_hits": [_hit_to_dict(h) for h in hits]}
