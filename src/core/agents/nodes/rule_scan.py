"""RuleScanner 节点：加载 active 规则，按领域对文档块执行规则扫描。

W18：按 app.yaml rule_engine.min_confidence 过滤低置信命中，降低误报；
方向③调阈值杠杆：规则 rule_content.min_confidence 覆盖全局（只影响本规则）。
"""

import re
from dataclasses import asdict

from src.core.agents.state import ReviewState
from src.core.rule_engine import RuleHit, rule_scanner
from src.core.rule_engine.consistency import scan_consistency
from src.core.rule_engine.pii_scan import scan_pii, scan_pii_from_spans
from src.infrastructure.database.mysql import SessionLocal
from src.models import Rule
from src.parsers.base import TextBlock
from src.utils.config import settings


def _hit_to_dict(hit: RuleHit) -> dict:
    data = asdict(hit)
    regs = list(data.get("related_regulations") or [])
    data["related_regulations"] = regs
    # 口径统一：LLM 侧产出的是 `regulation`（字符串），规则侧此前只填 `related_regulations`，
    # 导致报告/接口里规则命中的"引用"字段为空，任何按 `regulation` 统计的引用支撑率
    # 都会把规则检出误判为"无依据"（2026-10-22 实测：38%/47% → 合并口径 81%/84%）。
    # 这里补一个主引用（取首条），保留完整列表，导出器与旧消费者都不受影响。
    if not str(data.get("regulation") or "").strip():
        if regs:
            first = str(regs[0]).replace("《", "").replace("》", "").strip()
            # 与 LLM 侧对齐成"法规名 第X条"（LLM 产出带空格）
            data["regulation"] = re.sub(
                r"(第[一二三四五六七八九十百零〇0-9]+条)", r" \1", first, count=1
            ).strip()
        else:
            data["regulation"] = ""  # 键始终存在，消费方不必再判 None/缺键
    return data


def rule_scan(state: ReviewState) -> dict:
    db = SessionLocal()
    try:
        # 双保险：is_active 是运行期开关，status 是发布门禁，两者同时满足才参与扫描
        rules = (
            db.query(Rule).filter(Rule.is_active == 1, Rule.status == "active").all()
        )
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
    # 内置 PII 检测（R1-1）：代码内置不可停用，材料含客户身份/联系方式一票命中；
    # 不受规则表/领域路由约束（与领域无关），confidence=1.0 不受 min_confidence 过滤
    # 方案 A：优先消费解析脱敏时采集的命中元数据（脱敏后文本正则扫不出 PII）；
    # 无元数据时（如历史 state / 单测直构）回退为对文本直接扫描
    mask_spans = state.get("mask_spans") or []
    if mask_spans:
        hits = hits + scan_pii_from_spans(mask_spans)
    else:
        hits = hits + scan_pii(blocks)
    # 内置勾稽检测（R2-2）：markdown 表格算术一致性（模板未识别的表静默跳过，
    # 零误报优先）；confidence=1.0 同样不过滤
    # 注意：上面的 blocks 已经是 TextBlock 列表，此处直接复用——
    # 曾误写为对 blocks 再做一次 dict→TextBlock 转换（b["text"]），
    # 导致任何非空文档的任务执行时 TypeError（'TextBlock' object is not subscriptable）。
    hits = hits + scan_consistency(blocks)

    # W18：过滤低于置信度阈值的命中（app.yaml rule_engine.min_confidence）
    min_conf = settings.app_config("rule_engine").get("min_confidence", 0.5)
    # 调阈值杠杆：rule_content.min_confidence 覆盖全局（精调后只抬本规则）
    per_rule = {
        r.id: float(r.rule_content.get("min_confidence"))
        for r in rules
        if (r.rule_content or {}).get("min_confidence") is not None
    }
    if min_conf > 0 or per_rule:
        hits = [
            h for h in hits
            if h.confidence >= per_rule.get(h.rule_id, min_conf)
        ]

    return {"rule_hits": [_hit_to_dict(h) for h in hits]}
