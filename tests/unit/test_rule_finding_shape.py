"""规则命中 → 报告字段的一致性契约。

背景（2026-10-22 实测）：LLM 侧产出 `regulation`（如"商业银行理财业务监督管理办法 第二十六条"），
规则侧此前只填 `related_regulations`（"《法规》第X条"）列表，`regulation` 缺失/为空。
后果：任何按 `regulation` 统计"引用支撑率"的口径都会把规则检出误判为"无依据"——
实测同一份报告 38%/47% → 合并口径 81%/84%。这里锁住"规则命中必须也带主引用"。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.agents.nodes.rule_scan import _hit_to_dict  # noqa: E402
from src.core.rule_engine.engine import RuleHit  # noqa: E402


def _hit(**kw) -> RuleHit:
    base = dict(
        rule_id=2,
        rule_name="禁止刚性兑付承诺",
        domain="banking",
        severity="high",
        rule_type="regex",
        matched_text="保本保收益",
        char_start=0,
        char_end=5,
        page=1,
        paragraph=1,
        confidence=0.9,
    )
    base.update(kw)
    return RuleHit(**base)


def test_rule_hit_fills_primary_regulation_from_related():
    d = _hit_to_dict(
        _hit(
            related_regulations=[
                "《关于规范金融机构资产管理业务的指导意见》第十九条",
                "《商业银行理财业务监督管理办法》第二十六条",
            ]
        )
    )
    # 主引用取首条，去掉书名号，并按 LLM 风格在条号前留空格
    assert d["regulation"] == "关于规范金融机构资产管理业务的指导意见 第十九条"
    # 完整列表保留，导出器（docx/pdf）仍能逐条列出
    assert len(d["related_regulations"]) == 2


def test_rule_hit_without_related_regulations_has_empty_string_key():
    d = _hit_to_dict(_hit())
    assert d["regulation"] == ""      # 键必须存在，消费方不必判缺键
    assert d["related_regulations"] == []


def test_rule_hit_keeps_existing_regulation():
    """若上游已显式给出 regulation，不被覆盖。"""
    h = _hit(related_regulations=["《某办法》第三条"])
    h_dict = _hit_to_dict(h)
    h_dict["regulation"] = "保留原值"  # 模拟上游已赋值
    assert h_dict["regulation"] == "保留原值"


def test_regulation_string_has_no_book_title_marks():
    d = _hit_to_dict(_hit(related_regulations=["《X办法》第五条"]))
    assert "《" not in d["regulation"] and "》" not in d["regulation"]


def test_conflict_resolve_keeps_rule_citation():
    """合并到报告时不能把规则的主引用丢掉（2026-10-22 实测：报告里又是"无主引用"）。"""
    from src.core.agents.nodes.conflict_resolve import conflict_resolve

    state = {
        "llm_findings": [],
        "matched_articles": [],
        "tool_articles": [],
        "vlm_findings": [],
        "rule_hits": [
            _hit_to_dict(
                _hit(
                    related_regulations=["《关于规范金融机构资产管理业务的指导意见》第十九条"]
                )
            )
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[0]["regulation"] == "关于规范金融机构资产管理业务的指导意见 第十九条"
    assert merged[0]["related_regulations"] == [
        "《关于规范金融机构资产管理业务的指导意见》第十九条"
    ]
