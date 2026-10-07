"""翻案归因管道单测（R4-1）：mock DB 与 LLM，验证翻案识别/归因分类/报告结构.

不连真实数据库——_fetch_overturns/_fetch_stats 的 SQL 逻辑通过
monkeypatch SessionLocal（SQLite 内存库建最小表）或直接测纯聚合函数。
归因走 FakeLLM（llm.complete 接口）。
"""

import json

from scripts.evaluate import overturn_review as ov


class FakeResult:
    content = '{"category": "rule_missing", "evidence": "规则库无此类模式"}'
    usage = None


class FakeLLM:
    """llm.complete 接口（与 QwenClient 一致）。"""

    def __init__(self, content=None):
        self._content = content or FakeResult.content
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return FakeResult() if self._content is FakeResult.content else _FakeResp(self._content)


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.usage = None


class _FakeLog:
    def __init__(self, log_id, detail, username="合规张三", at="2026-09-15T10:00:00"):
        self.id = log_id
        self.detail = detail
        self.username = username
        self.created_at = None
        self.resource_id = "501"
        self.action = "result.confirm"
        self._at = at


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._items


class _FakeDB:
    """get(id) → ReviewResult 形态；query(AuditLog) → 审计行。"""

    def __init__(self, logs, results):
        self._logs = logs
        self._results = results

    def query(self, model):
        return _FakeQuery(self._logs)

    def get(self, model, rid):
        return self._results.get(str(rid)) or self._results.get(rid)

    def close(self):
        pass


class _FakeReviewResult:
    def __init__(self):
        self.id = 501
        self.original_text = "年化收益率高达 99%，稳赚不赔"
        self.description = "夸大收益表述命中"
        self.violation_type = "llm"
        self.risk_level = "high"


_FP_FLIP = {
    "before_status": "confirmed",
    "verdict": "false_positive",
    "before_auto_confirmed": True,
}


def test_fetch_overturns_filters_by_status_flip():
    logs = [
        _FakeLog(1, json.dumps({"before_status": "confirmed", "verdict": "confirmed"})),  # 非翻案
        _FakeLog(2, json.dumps(_FP_FLIP)),
        _FakeLog(3, "not-json"),  # 坏行跳过
    ]
    db = _FakeDB(logs, {"501": _FakeReviewResult()})
    overturns = ov._fetch_overturns(db, None, None)
    assert len(overturns) == 1
    assert overturns[0]["before_status"] == "confirmed"
    assert overturns[0]["verdict"] == "false_positive"
    assert overturns[0]["before_auto_confirmed"] is True


def test_fetch_stats_counts_flips():
    logs = [
        _FakeLog(1, json.dumps({"before_status": "confirmed", "verdict": "confirmed"})),
        _FakeLog(2, json.dumps(_FP_FLIP)),
        _FakeLog(3, json.dumps({"before_status": "pending_confirm", "verdict": "confirmed"})),
    ]
    stats = ov._fetch_stats(_FakeDB(logs, {}), None, None)
    # 口径修正（2026-10-05）：pending→confirmed 是常规复核，不计入翻案
    assert stats == {"human_actions": 3, "overturns": 1, "auto_confirm_overturns": 1}


def test_pending_confirm_is_not_overturn():
    """状态与判定不同命名空间：常规复核（pending → 任一判定）不是翻案。"""
    logs = [
        _FakeLog(1, json.dumps({"before_status": "pending_confirm", "verdict": "confirmed"})),
        _FakeLog(2, json.dumps({"before_status": "pending_confirm", "verdict": "false_positive"})),
    ]
    stats = ov._fetch_stats(_FakeDB(logs, {}), None, None)
    assert stats["human_actions"] == 2
    assert stats["overturns"] == 0


def test_is_overturn_boundary_cases():
    assert ov._is_overturn("confirmed", "false_positive") is True
    assert ov._is_overturn("false_positive", "confirmed") is True
    assert ov._is_overturn("confirmed", "confirmed") is False
    assert ov._is_overturn("pending_confirm", "confirmed") is False
    assert ov._is_overturn(None, "confirmed") is False

    # _is_overturn 口径与 result_trail 同源：两端判定必须一致
    from src.services.result_trail import _JUDGED_STATUSES

    assert ov._JUDGED_STATUSES == _JUDGED_STATUSES


def test_attribute_parses_llm_category():
    item = {
        "original_text": "稳赚不赔",
        "before_status": "confirmed",
        "violation_type": "rule",
        "risk_level": "high",
        "description": "命中禁止性表述",
        "verdict": "false_positive",
    }
    result = ov._attribute(FakeLLM(), item)
    assert result["category"] == "rule_missing"
    assert result["evidence"]


def test_attribute_failure_degrades_to_unattributed():
    class _BadLLM:
        def complete(self, messages):
            raise RuntimeError("LLM down")

    item = {
        "original_text": "x",
        "before_status": "confirmed",
        "verdict": "false_positive",
        "violation_type": "rule",
        "risk_level": "high",
        "description": "",
    }
    result = ov._attribute(_BadLLM(), item)
    assert result["category"] == "unattributed"


def test_build_report_full_pipeline(monkeypatch):
    """端到端：审计行 → 翻案识别 → 归因 → 报告结构（不落库，mock DB 层）。"""
    logs = [
        _FakeLog(2, json.dumps(_FP_FLIP)),
        _FakeLog(3, json.dumps({"before_status": "pending_confirm", "verdict": "confirmed"})),
    ]
    fake_db = _FakeDB(logs, {"501": _FakeReviewResult()})
    monkeypatch.setattr(ov, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(ov, "get_llm", lambda: None)

    report = ov.build_report("2026-09", limit=0, use_llm=False)
    assert report["month"] == "2026-09"
    # 口径修正后：仅 confirmed→fp 计翻案；pending→confirmed 是常规复核
    assert report["stats"]["overturns"] == 1
    assert report["overturn_rate"] is not None
    # use_llm=False → 归因留空（未启用 LLM 归因），报告仍完整
    assert report["overturns"][0]["attribution"]["category"] == "unattributed"
    assert "不自动修改" in report["note"]


def test_build_report_with_llm_attribution(monkeypatch):
    logs = [
        _FakeLog(2, json.dumps({"before_status": "confirmed", "verdict": "false_positive"})),
    ]
    fake_db = _FakeDB(logs, {"501": _FakeReviewResult()})
    monkeypatch.setattr(ov, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(ov, "get_llm", lambda: FakeLLM())

    report = ov.build_report("2026-09", limit=0, use_llm=True)
    assert report["category_counts"] == {"rule_missing": 1}
    assert any("规则挖掘" in k for k in report["pipeline_suggestions"])
