"""成本归因与待核验清单：reducer 合并 / 牌价预估 / 报告聚合 / Markdown 渲染 / 落库字段。"""

import pytest
from sqlalchemy import text
from src.core.agents.state import _merge_llm_usage
from src.core.llm.pricing import estimate_cost, resolve_price
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown

# ---------- llm_usage reducer（state.py） ----------


def test_merge_llm_usage_sums_numbers_keeps_model():
    a = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "calls": 2,
        "model": "qwen-plus",
    }
    b = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60, "calls": 1}
    merged = _merge_llm_usage(a, b)
    assert merged["total_tokens"] == 180
    assert merged["calls"] == 3
    assert merged["model"] == "qwen-plus"


def test_merge_llm_usage_none_and_empty():
    assert _merge_llm_usage(None, None) is None
    # 零用量（仅 model/failed_blocks，无真实 token）不落 state，保持 no-LLM 缺省语义
    assert _merge_llm_usage({"model": "m", "failed_blocks": 1}, None) is None
    # 检索侧先跑（无 model）时，后到的 llm_scan 用量能补上 model
    merged = _merge_llm_usage({"total_tokens": 30, "calls": 1}, {"model": "qwen-flash"})
    assert merged["model"] == "qwen-flash"
    assert merged["total_tokens"] == 30


# ---------- 牌价预估（pricing.py） ----------


def test_resolve_price_family_prefix():
    # 新模型名（qwen3.7-flash 等）按家族子串归档
    assert resolve_price("qwen3.7-flash") == resolve_price("qwen-flash")
    assert resolve_price("qwen-plus-latest") == resolve_price("qwen-plus")
    assert resolve_price("totally-unknown-model") == (None, None)


def test_estimate_cost_known_model():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    est = estimate_cost(usage, "qwen-plus")
    assert est["priced"] is True
    assert abs(est["estimated_cost_cny"] - 2.8) < 1e-6  # 0.8 + 2.0


def test_estimate_cost_unknown_model():
    est = estimate_cost({"prompt_tokens": 1_000_000}, "mystery-model")
    assert est["priced"] is False
    assert est["estimated_cost_cny"] is None


# ---------- 报告聚合（generator.py） ----------


def _finding(**kw):
    base = {"original_text": "稳赚不赔", "risk_level": "high", "page": 1, "paragraph": 2}
    base.update(kw)
    return base


def test_build_report_pending_verification_buckets():
    findings = [
        _finding(violation_type="hybrid", evidence_supported=False),  # 证据待核
        _finding(violation_type="llm", evidence_supported=None),  # 无引用
        _finding(violation_type="rule"),  # 规则命中：结构化溯源，不进清单
        _finding(violation_type="rule", rule_name="面向老年人收益承诺"),  # 无适当性字样
        _finding(violation_type="rule", description="适当性：诱导绕过测评"),  # 适当性材料
    ]
    report = build_report(1, "产品.docx", "banking", findings)
    pending = report["pending_verification"]
    assert len(pending) == 3
    assert report["summary"]["pending_verification"] == 3
    assert "法规原文" in pending[0]["reasons"][0]
    assert pending[0]["risk_level"] == "high"
    # 适当性条目带材料佐证原因
    suit = [p for p in pending if any("产品风险等级" in r for r in p["reasons"])]
    assert len(suit) == 1


def test_build_report_pending_sorted_high_first():
    findings = [
        _finding(violation_type="llm", evidence_supported=None, risk_level="low"),
        _finding(violation_type="hybrid", evidence_supported=False, risk_level="high"),
    ]
    pending = build_report(1, "d.docx", None, findings)["pending_verification"]
    assert [p["risk_level"] for p in pending] == ["high", "low"]


def test_build_report_no_pending():
    findings = [_finding(violation_type="rule", evidence_supported=True)]
    report = build_report(1, "d.docx", None, findings)
    assert report["pending_verification"] == []
    assert report["summary"]["pending_verification"] == 0


def test_build_report_cost_enrichment_no_mutation():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
        "calls": 1,
        "model": "qwen-plus",
    }
    report = build_report(1, "d.docx", None, [], llm_usage=usage)
    enriched = report["llm_usage"]
    assert enriched["priced"] is True
    assert enriched["estimated_cost_cny"] > 0
    assert enriched["calls"] == 1
    # 原 dict 不被就地污染（state 里的 llm_usage 保持原样）
    assert "priced" not in usage


# ---------- Markdown 渲染（markdown.py） ----------


def test_markdown_renders_cost_and_pending_section():
    findings = [_finding(violation_type="hybrid", evidence_supported=False)]
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 0,
        "total_tokens": 1000,
        "calls": 1,
        "model": "qwen-plus",
    }
    md = render_markdown(build_report(1, "d.docx", "banking", findings, llm_usage=usage))
    assert "预估 ¥" in md and "按牌价" in md
    assert "## 五、待人工核验清单" in md
    assert "法规原文" in md


def test_markdown_unpriced_model_only_tokens():
    usage = {"total_tokens": 100, "calls": 1, "model": "mystery-model"}
    md = render_markdown(build_report(1, "d.docx", None, [], llm_usage=usage))
    assert "预估 ¥" not in md
    assert "没有需要人工补充核验" in md


# ---------- 落库字段（需本地 MySQL；列由迁移脚本/create_all 提供） ----------


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_tasks_llm_usage_column():
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    rows = db.execute(text("SHOW COLUMNS FROM review_tasks LIKE 'llm_usage'")).fetchall()
    db.close()
    assert len(rows) == 1
