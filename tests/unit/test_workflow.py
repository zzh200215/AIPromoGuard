import pytest
from src.core.agents.nodes.classify import _detect_domain, classify
from src.core.agents.nodes.conflict_resolve import conflict_resolve
from src.core.agents.nodes.risk_assess import risk_assess
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown


def test_detect_domain_insurance():
    assert _detect_domain("本保险产品保额100万，保费每年5000元，理赔快速") == "insurance"


def test_detect_domain_fund():
    assert _detect_domain("本基金净值1.2，申购赎回免费，由基金经理管理") == "fund"


def test_detect_domain_banking():
    assert _detect_domain("本理财产品年化收益4%，净值型产品") == "banking"


def test_classify_node_returns_domain():
    state = {"text": "保险产品 保费 理赔 投保"}
    assert classify(state) == {"domain": "insurance"}


def test_conflict_resolve_rule_priority():
    state = {
        "rule_hits": [
            {
                "rule_id": 1,
                "rule_name": "禁止保本保收益",
                "matched_text": "保本保收益",
                "page": 1,
                "paragraph": 2,
                "confidence": 0.95,
                "severity": "high",
                "description": "d",
            }
        ],
        "llm_findings": [
            {"issue": "保本承诺", "original_text": "保本保收益", "severity": "high", "reason": "r"},
            {
                "issue": "夸大宣传",
                "original_text": "稳赚不赔",
                "severity": "medium",
                "reason": "r2",
            },
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert len(merged) == 3
    sources = [m["source"] for m in merged]
    assert sources.count("rule") == 1
    assert "hybrid" in sources  # 规则与 LLM 交叉命中 → 交叉验证
    llm_only = next(m for m in merged if m["source"] == "llm")
    assert llm_only["flag"] == "建议关注"


def test_risk_assess_composite_score():
    findings = [
        {"type": "禁止性", "severity": "medium", "source": "rule", "confidence": 0.95},
        {"type": "限制性", "severity": "medium", "source": "hybrid", "confidence": 0.7},
        {"type": "披露性", "severity": "low", "source": "llm", "confidence": 0.5},
    ]
    out = risk_assess({"merged_findings": findings})["merged_findings"]
    # 禁止性+高置信度→high；限制性+双引擎→medium；披露性+低→low
    assert [f["risk_level"] for f in out] == ["high", "medium", "low"]
    assert all(f.get("risk_reason") for f in out)
    assert "规则+LLM双引擎确认" in out[1]["risk_reason"]


def test_conflict_resolve_rule_type_from_severity(monkeypatch):
    """规则条目按 severity 推导违规类型，修复规则路被一律按披露性计分的系统性低估。"""
    from src.services import graph_service

    monkeypatch.setattr(graph_service, "similar_cases", lambda *a, **k: [])
    state = {
        "rule_hits": [
            {
                "rule_id": 1,
                "rule_name": "禁止刚性兑付承诺",
                "matched_text": "保本保收益",
                "page": 1,
                "paragraph": 1,
                "confidence": 0.95,
                "severity": "high",
            }
        ],
        "llm_findings": [],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[0]["type"] == "禁止性"
    # 高严重度规则命中：禁止性(3)+high(1)+置信度≥0.9(1)=5 → high（修复前恒 medium）
    out = risk_assess({"merged_findings": merged})["merged_findings"]
    assert out[0]["risk_level"] == "high"
    # 中低严重度映射：medium→限制性、low→披露性
    for sev, expected in (("medium", "限制性"), ("low", "披露性")):
        single = conflict_resolve(
            {"rule_hits": [{**state["rule_hits"][0], "severity": sev}], "llm_findings": []}
        )["merged_findings"]
        assert single[0]["type"] == expected


def test_build_report_summary():
    findings = [{"risk_level": "high"}, {"risk_level": "high"}, {"risk_level": "medium"}]
    report = build_report(1, "产品.docx", "banking", findings)
    assert report["summary"]["total_violations"] == 3
    assert report["summary"]["high_risk"] == 2
    assert report["summary"]["medium_risk"] == 1


def test_conflict_resolve_carries_related_regulations():
    state = {
        "rule_hits": [
            {
                "rule_id": 1,
                "rule_name": "禁止保本保收益",
                "matched_text": "保本保收益",
                "page": 1,
                "paragraph": 1,
                "confidence": 0.95,
                "severity": "high",
                "description": "d",
                "related_regulations": ["《商业银行理财业务监督管理办法》第二十六条"],
            }
        ],
        "llm_findings": [],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert merged[0]["related_regulations"] == ["《商业银行理财业务监督管理办法》第二十六条"]


def test_render_markdown_contains_sections():
    report = build_report(
        1,
        "测试产品.txt",
        "banking",
        [
            {
                "source": "rule",
                "risk_level": "high",
                "rule_name": "禁止保本保收益",
                "original_text": "保本保收益",
                "page": 1,
                "paragraph": 2,
                "suggestion": "删除该表述",
            }
        ],
    )
    md = render_markdown(report)
    assert "金融产品合规审查报告" in md
    assert "审查摘要" in md
    assert "违规明细" in md
    assert "相关法规" in md
    assert "删除该表述" in md


def test_render_pdf():
    from src.core.report.pdf import find_cjk_font, render_pdf

    if find_cjk_font() is None:
        pytest.skip("未找到 CJK 字体，跳过 PDF 测试")
    report = build_report(
        1,
        "测试产品.txt",
        "banking",
        [
            {
                "risk_level": "high",
                "source": "rule",
                "type": "禁止性",
                "rule_name": "禁止保本保收益",
                "original_text": "保本保收益",
                "page": 1,
                "paragraph": 1,
                "confidence": 0.95,
            }
        ],
    )
    data = render_pdf(report)
    assert data[:4] == b"%PDF"


def test_llm_scan_degrades_without_key(monkeypatch):
    import src.core.agents.nodes.llm_scan as mod

    monkeypatch.setattr(mod, "get_llm", lambda: None)
    state = {"blocks": [{"text": "保本", "page": 1, "paragraph": 1}], "matched_articles": []}
    result = mod.llm_scan(state)
    assert result["llm_findings"] == []
    assert result["llm_usage"] is None


def test_graph_end_to_end():
    from src.infrastructure.database.mysql import SessionLocal

    try:
        db = SessionLocal()
        from src.models import Rule

        rule_count = db.query(Rule).count()
        db.close()
    except Exception:
        pytest.skip("数据库不可用")
    if rule_count == 0:
        pytest.skip("规则库为空")

    from src.core.agents.graph import run_review

    sample = "本理财产品保本保收益，零风险，预期年化收益率5.8%，本金无忧，稳赚不赔。"
    initial = {
        "task_id": 9999,
        "document_name": "测试产品.txt",
        "document_path": "/tmp/测试产品.txt",
        "doc_type": "txt",
        "text": sample,
        "blocks": [
            {"text": sample, "page": 1, "paragraph": 1, "heading": False}
        ],
    }
    result = run_review(initial)
    report = result["report"]
    # 领域路由已生效：分类识别为 banking，走 domain_banking 子图
    assert result["domain"] == "banking"
    assert report["summary"]["total_violations"] > 0
    assert "task_9999.json" in (result["report_path"] or "")
    assert all(v["risk_level"] in ("high", "medium", "low") for v in report["violations"])


def test_graph_end_to_end_general_fallback():
    """领域识别失败（domain=None）时走兜底子图，流程仍产出报告。"""
    from src.infrastructure.database.mysql import SessionLocal

    try:
        db = SessionLocal()
        from src.models import Rule

        rule_count = db.query(Rule).count()
        db.close()
    except Exception:
        pytest.skip("数据库不可用")
    if rule_count == 0:
        pytest.skip("规则库为空")

    from src.core.agents.graph import run_review

    # 纯中性文本，无法命中任何领域关键词 → classify 返回 None → domain_general 兜底
    sample = "这是一份日常的工作文档，内容包括日程安排与会议记录，不涉及任何产品表述。"
    initial = {
        "task_id": 9998,
        "document_name": "中性文档.txt",
        "document_path": "/tmp/中性文档.txt",
        "doc_type": "txt",
        "text": sample,
        "blocks": [
            {"text": sample, "page": 1, "paragraph": 1, "heading": False}
        ],
    }
    result = run_review(initial)
    assert result["domain"] is None  # 未被识别领域
    assert "task_9998.json" in (result["report_path"] or "")
    assert result["report"]["summary"]["total_violations"] >= 0


def test_risk_assess_attaches_relevant_graph_cases(monkeypatch):
    """相似度达标的图谱案例被附加并抬高风险（PRD §3.2.8 关联处罚案例）。"""
    from src.core.agents.nodes import risk_assess as ra
    from src.services import graph_service

    strong = [{"case_name": "某银行违规承诺保本保收益案", "penalty_org": "银保监会",
               "penalty_result": "罚款150万", "similarity": 0.9}]
    monkeypatch.setattr(graph_service, "similar_cases", lambda *a, **k: strong)

    findings = [{"type": "限制性", "severity": "medium", "source": "rule",
                 "confidence": 0.8, "original_text": "承诺保本保收益"}]
    out = ra.risk_assess({"merged_findings": findings, "domain": "banking"})["merged_findings"]
    assert out[0]["related_cases"] == strong
    assert "关联历史处罚案例" in out[0]["risk_reason"]
    # 限制性(2)+案例佐证(1)+medium(0)+conf<0.9(0)=3 → medium（无案例则为 2 仍 medium，但不加原因）
    assert out[0]["risk_level"] == "medium"


def test_risk_assess_filters_weak_cases(monkeypatch):
    """相似度低于阈值的案例被过滤，不抬高风险。"""
    from src.core.agents.nodes import risk_assess as ra
    from src.services import graph_service

    weak = [{"case_name": "某不相关案例", "penalty_org": "某局",
             "penalty_result": "警告", "similarity": 0.2}]
    monkeypatch.setattr(graph_service, "similar_cases", lambda *a, **k: weak)

    findings = [{"type": "披露性", "severity": "low", "source": "llm",
                 "confidence": 0.5, "original_text": "风险提示不充分"}]
    out = ra.risk_assess({"merged_findings": findings, "domain": "insurance"})["merged_findings"]
    assert out[0]["related_cases"] == []  # 弱匹配被过滤
    assert out[0]["risk_level"] == "low"


def test_classify_config_driven_new_domain(monkeypatch):
    """W19：app.yaml 加新领域配置后，分类器零代码改动即识别（可行性验证）。"""
    from types import SimpleNamespace

    from src.core.agents.nodes import classify as c

    s = SimpleNamespace()
    s.app_config = lambda section: (
        {"trust": {"label": "信托", "keywords": ["信托", "受托人", "信托计划"]}}
        if section == "domains"
        else {}
    )
    monkeypatch.setattr("src.core.agents.nodes.classify.settings", s)
    assert c._detect_domain("本信托计划由受托人设立，管理信托财产") == "trust"
    # 配置缺省时回退内置三领域
    monkeypatch.setattr(
        "src.core.agents.nodes.classify.settings",
        SimpleNamespace(app_config=lambda section: {}),
    )
    assert c._detect_domain("本信托计划由受托人管理") is None
