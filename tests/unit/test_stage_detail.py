"""stage_log 过程明细（_stage_detail）与 _wrap 接线测试——前端审查轨迹面板数据源。

覆盖：各节点明细提取形状、可选字段条件出现、LLM 降级路径（usage=None）、
未知节点返回 None（不污染 stage_log）、_wrap 把 detail 挂进 stage_log 条目。
"""

from src.core.agents.graph import _stage_detail, _wrap


def test_classify_detail():
    assert _stage_detail("classify", {"domain": "fund"}) == {"domain": "fund"}


def test_classify_detail_domain_none():
    # 识别失败回退兜底子图：domain=None 仍保留键（前端显示"通用"语义）
    assert _stage_detail("classify", {}) == {"domain": None}


def test_regulation_match_detail_top_articles_capped():
    articles = [
        {"regulation_name": f"法规{i}", "article_no": f"第{i}条"} for i in range(5)
    ]
    d = _stage_detail("regulation_match", {"matched_articles": articles})
    assert d["article_count"] == 5
    assert len(d["top_articles"]) == 3
    assert d["top_articles"][0] == {"name": "法规0", "article_no": "第0条"}
    # agentic 未开启时无该键（可选字段条件出现）
    assert "agentic_rounds" not in d


def test_regulation_match_detail_agentic_optional():
    d = _stage_detail(
        "regulation_match",
        {"matched_articles": [], "retrieval_meta": {"rounds": 2, "added": 3}},
    )
    assert d["agentic_rounds"] == 2
    assert d["agentic_added"] == 3


def test_regulation_match_detail_name_truncated():
    long_name = "超长法规名称" * 20
    d = _stage_detail(
        "regulation_match",
        {"matched_articles": [{"regulation_name": long_name, "article_no": "第一条"}]},
    )
    assert len(d["top_articles"][0]["name"]) <= 60


def test_rule_scan_detail():
    assert _stage_detail("rule_scan", {"rule_hits": [{}, {}]}) == {"hit_count": 2}


def test_llm_scan_detail_with_usage():
    d = _stage_detail(
        "llm_scan",
        {
            "llm_findings": [{}],
            "llm_usage": {"total_tokens": 1234, "failed_blocks": 1, "model": "m"},
        },
    )
    assert d["finding_count"] == 1
    assert d["tokens"] == 1234
    assert d["failed_blocks"] == 1
    assert d["model"] == "m"


def test_llm_scan_detail_degraded_no_key():
    # 无 API Key 降级：usage=None 不崩，字段保留 None（前端显示"未启用"）；
    # prompt 版本号来自注册表（随版本演进自动同步）；precedents=无记忆时 0
    from src.core.llm.prompts.registry import get_prompt

    d = _stage_detail("llm_scan", {"llm_findings": [], "llm_usage": None})
    assert d == {
        "finding_count": 0,
        "tokens": None,
        "failed_blocks": None,
        "model": None,
        "prompt": f"review@{get_prompt('review').version}",
        "precedents": 0,
        "channel": "standard",
    }


def test_llm_scan_detail_precedents_observed():
    # 先例记忆可观测：precedent_meta.injected 透传进 stage_log（前端轨迹可见）
    d = _stage_detail(
        "llm_scan",
        {"llm_findings": [], "llm_usage": None, "precedent_meta": {"units": 4, "injected": 7}},
    )
    assert d["precedents"] == 7


def test_conflict_resolve_detail_by_source():
    merged = [
        {"source": "rule"},
        {"source": "llm"},
        {"source": "llm"},
        {"source": "hybrid"},
    ]
    d = _stage_detail("conflict_resolve", {"merged_findings": merged})
    assert d == {"merged_count": 4, "by_source": {"rule": 1, "llm": 2, "hybrid": 1}}


def test_conflict_resolve_detail_missing_source():
    d = _stage_detail("conflict_resolve", {"merged_findings": [{}]})
    assert d["by_source"] == {"unknown": 1}


def test_human_review_detail_disabled():
    # 关卡未启用（节点直通，无 human_review 键）
    assert _stage_detail("human_review", {}) == {"enabled": False}


def test_human_review_detail_enabled_no_pending():
    # 关卡启用但无待复核项（required=False 与"未启用"语义区分开）
    assert _stage_detail("human_review", {"human_review": {"required": False}}) == {
        "enabled": True,
        "required": False,
        "reviewed_count": 0,
        "rejected_count": 0,
    }


def test_human_review_detail_reviewed():
    d = _stage_detail(
        "human_review",
        {
            "human_review": {
                "required": True,
                "rejected_indexes": [0, 3],
                "reviewed_count": 5,
            }
        },
    )
    assert d == {"enabled": True, "required": True, "reviewed_count": 5, "rejected_count": 2}


def test_risk_assess_detail():
    findings = [
        {"risk_level": "high", "related_cases": [{"x": 1}]},
        {"risk_level": "low", "related_cases": []},
        {"risk_level": "high"},
    ]
    d = _stage_detail("risk_assess", {"merged_findings": findings})
    assert d["by_risk"] == {"high": 2, "low": 1}
    assert d["with_cases"] == 1


def test_report_detail():
    d = _stage_detail("report", {"report": {"summary": {"total_violations": 7}}})
    assert d == {"total_violations": 7}


def test_report_detail_missing_summary():
    assert _stage_detail("report", {}) == {"total_violations": None}


def test_unknown_node_returns_none():
    assert _stage_detail("nope", {}) is None


def test_wrap_attaches_detail_to_stage_log():
    wrapped = _wrap(lambda s: {"domain": "fund"}, "classify")
    out = wrapped({"task_id": 1})
    entry = out["stage_log"]["classify"]
    assert entry["status"] == "completed"
    assert isinstance(entry["cost_ms"], int)
    assert entry["detail"] == {"domain": "fund"}


def test_wrap_node_returning_none_keeps_stage_log():
    # human_review 未启用时节点返回 {}（_wrap 归一为 {}）——stage_log 仍记录
    wrapped = _wrap(lambda s: None, "human_review")
    out = wrapped({})
    entry = out["stage_log"]["human_review"]
    assert entry["status"] == "completed"
    assert entry["detail"] == {"enabled": False}
