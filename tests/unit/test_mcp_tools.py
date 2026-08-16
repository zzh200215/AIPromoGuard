"""MCP 工具层单测：scan_text / search_regulations / review_text 与 server 注册。

工具实现复用 workflow 节点（rule_scan / regulation_match / llm_scan /
conflict_resolve），此处验证参数透传、输出裁剪与降级路径。
"""

import asyncio

import pytest

from src.infrastructure.database.mysql import SessionLocal
from src.models import Rule
from src.mcp_server import tools


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.query(Rule).count()
        db.close()
        return True
    except Exception:
        return False


VIOLATION_TEXT = "本理财产品由我行全程担保，保本保收益，历史年化收益率12%以上。"
CLEAN_TEXT = "本产品为非保本浮动收益型理财产品，不保证本金及收益，投资须谨慎。"


# ---------- scan_text ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_scan_text_finds_violation():
    result = tools.scan_text(VIOLATION_TEXT)
    assert result["total_hits"] >= 1
    names = {h["rule_name"] for h in result["hits"]}
    assert any("保本" in n or "刚性兑付" in n for n in names)
    hit = result["hits"][0]
    assert {"rule_name", "severity", "matched_text", "confidence"} <= set(hit)


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_scan_text_clean_text_no_hit():
    result = tools.scan_text(CLEAN_TEXT)
    assert result["total_hits"] == 0


# ---------- search_regulations ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_search_regulations_returns_articles():
    result = tools.search_regulations("理财产品 承诺保本 收益", top_k=3)
    assert 1 <= result["total"] <= 3
    art = result["articles"][0]
    assert art["regulation_name"]
    assert art["content"]


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_search_regulations_top_k_clamped():
    result = tools.search_regulations("理财产品销售", top_k=99)
    assert result["total"] <= 20


# ---------- review_text ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_text_rule_only():
    result = tools.review_text(VIOLATION_TEXT, use_llm=False)
    assert result["llm_enabled"] is False
    assert result["llm_usage"] is None
    assert result["total_findings"] == result["rule_engine_hits"] >= 1
    assert all(f["source"] == "rule" for f in result["findings"])


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_text_merges_llm_findings(monkeypatch):
    """llm_scan 打桩返回一条 LLM 判定，验证 conflict_resolve 融合 source=llm。"""

    def fake_llm_scan(state):
        return {
            "llm_findings": [
                {
                    "type": "禁止性",
                    "issue": "夸大宣传历史业绩",
                    "original_text": "历史年化收益率12%以上",
                    "regulation": "理财公司理财产品销售管理暂行办法 第二十六条",
                    "reason": "夸大或片面宣传过往业绩",
                    "suggestion": "删除业绩承诺表述",
                    "severity": "medium",
                    "confidence": 0.8,
                    "page": 1,
                    "paragraph": 1,
                }
            ],
            "llm_usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(tools, "llm_scan", fake_llm_scan)
    monkeypatch.setattr(tools, "get_llm", lambda: object())  # 模拟已配置 key

    result = tools.review_text(VIOLATION_TEXT, use_llm=True)
    assert result["llm_enabled"] is True
    sources = {f["source"] for f in result["findings"]}
    assert "rule" in sources
    # LLM 判定进入融合结果；与规则命中重叠时升格为 hybrid（交叉确认），否则 llm
    assert sources & {"llm", "hybrid"}
    merged = next(f for f in result["findings"] if f["description"] == "夸大或片面宣传过往业绩")
    if merged["source"] == "llm":
        assert merged["flag"] == "建议关注"


# ---------- server 工具注册 ----------

def test_mcp_server_registers_three_tools():
    from src.mcp_server.server import mcp

    names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert names == ["scan_text", "search_regulations", "review_text"]


def test_mcp_server_wraps_tool_implementations(monkeypatch):
    """server 装饰的函数应代理到 tools 层（打桩验证透传）。"""
    import src.mcp_server.server as server_mod

    calls = {}

    def fake_scan(text, domain=None):
        calls["args"] = (text, domain)
        return {"total_hits": 0, "hits": []}

    monkeypatch.setattr(server_mod.tools, "scan_text", fake_scan)
    result = server_mod.scan_text("测试文本", domain="banking")
    assert result == {"total_hits": 0, "hits": []}
    assert calls["args"] == ("测试文本", "banking")
