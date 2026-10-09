"""视觉层审查（VLM）测试：归一/降级/conflict_resolve 合入/待核验/标签。"""

import pytest
from src.core.agents.nodes.conflict_resolve import conflict_resolve
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown
from src.services import visual_scan
from src.services.review_service import _auto_confirm
from src.utils.config import settings

_VLM_JSON = (
    '{"findings": ['
    '{"issue": "收益数字放大", "reason": "5.8% 用 72px 红字居中", '
    '"original_text": "预期年化收益率 5.8%", "severity": "high", '
    '"confidence": 0.9, "suggestion": "统一字号"},'
    '{"issue": "", "reason": "缺 issue 丢弃"},'
    '{"issue": "图形暗示", "severity": "critical", "confidence": 5}'
    ']}'
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50
    total_tokens = 150


class _FakeResp:
    def __init__(self, content=_VLM_JSON):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, resp):
        self._resp = resp
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


class _FakeChat:
    def __init__(self, resp):
        self.completions = _FakeCompletions(resp)


class _FakeClient:
    def __init__(self, resp):
        self.chat = _FakeChat(resp)


@pytest.fixture(autouse=True)
def _vlm_on(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "key")
    monkeypatch.setattr(settings, "vlm_enabled", True)
    monkeypatch.setattr(settings, "vlm_model", "qwen-vl-plus")


def _image(tmp_path, ext="png"):
    path = tmp_path / f"poster.{ext}"
    path.write_bytes(b"\x89fake-image-bytes")
    return str(path)


# ---------- scan_image_visual ----------


def _scan(tmp_path, client, ext="png", text="text"):
    return visual_scan.scan_image_visual(_image(tmp_path, ext), text, None, client)


def test_scan_success_normalizes_and_returns_usage(tmp_path):
    client = _FakeClient(_FakeResp())
    findings, usage, _numbers, _missing = _scan(tmp_path, client, text="预期年化收益率 5.8%")
    assert len(findings) == 2  # 缺 issue 的条目被丢弃
    first = findings[0]
    assert first["issue"] == "收益数字放大"
    assert first["severity"] == "high"
    assert first["confidence"] == 0.9
    second = findings[1]
    assert second["severity"] == "medium"  # critical 夹取回 medium
    assert second["confidence"] == 1.0  # 越界夹取到上界（0.7 仅用于缺失）
    assert usage["total_tokens"] == 150
    # 模型与图片走多模态消息结构
    assert client.chat.completions.kwargs["model"] == "qwen-vl-plus"
    content = client.chat.completions.kwargs["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_scan_no_key_degrades(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    assert _scan(tmp_path, _FakeClient(_FakeResp())) == ([], None, [], [])


def test_scan_disabled_degrades(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "vlm_enabled", False)
    assert _scan(tmp_path, _FakeClient(_FakeResp())) == ([], None, [], [])


def test_scan_client_error_degrades(tmp_path):
    assert _scan(tmp_path, _FakeClient(RuntimeError("boom"))) == ([], None, [], [])


def test_scan_unsupported_ext_skips_client(tmp_path):
    client = _FakeClient(RuntimeError("不应被调用"))
    assert _scan(tmp_path, client, ext="gif") == ([], None, [], [])


# ---------- find_ocr_missing（PR-6 图片级两路对照）----------


def test_find_ocr_missing_keeps_unread_numbers():
    """VLM 读到但图片 OCR 文字层没有的数字 → 进 missing（带位置=紧邻标签）。"""
    missing = visual_scan.find_ocr_missing(
        [{"value": "9.85", "context": "年化收益率"},
         {"value": "366", "context": "持有期限"}],
        "预期年化收益率 3.85%，产品期限 366 天",  # 366 读到 → 不算 missing
    )
    assert missing == [{"value": "9.85", "context": "年化收益率"}]


def test_find_ocr_missing_normalizes_before_compare():
    """归一后相等（千分位/尾零）算读到，不进 missing。"""
    missing = visual_scan.find_ocr_missing(
        [{"value": "50,000", "context": "认购金额"}, {"value": "3.80", "context": "费率"}],
        "认购金额 50000.00 元，费率 3.8%",
    )
    assert missing == []


def test_find_ocr_missing_filters_non_key_and_malformed():
    missing = visual_scan.find_ocr_missing(
        [None, {"value": "", "context": "收益率"}, {"value": "1", "context": ""}],
        "材料正文",
    )
    assert missing == []


def test_scan_success_returns_ocr_missing(tmp_path):
    """端到端：VLM 输出 visible_numbers 时按图片 OCR 文本切出 missing 子集。"""
    content = (
        '{"findings": [], "visible_numbers": ['
        '{"value": "9.85", "context": "年化收益率"},'
        '{"value": "366", "context": "持有期限"}]}'
    )
    findings, _usage, numbers, missing = _scan(
        tmp_path, _FakeClient(_FakeResp(content)), text="本产品期限 366 天"
    )
    assert findings == []
    assert [n["value"] for n in numbers] == ["9.85", "366"]
    assert [m["value"] for m in missing] == ["9.85"]


def test_parse_extracts_visible_numbers(tmp_path):
    """R2-3：VLM 输出含 visible_numbers 时完整解析（findings 与数字分离）。"""
    content = (
        '{"findings": [{"issue": "收益数字放大", "reason": "红字", '
        '"original_text": "9.85%", "severity": "high", "confidence": 0.9}], '
        '"visible_numbers": [{"value": "9.85", "context": "年化收益率"}, '
        '{"value": "366", "context": "持有期限"}]}'
    )
    findings, numbers = visual_scan._parse_vlm_output(content)
    assert len(findings) == 1
    assert [n["value"] for n in numbers] == ["9.85", "366"]


def test_parse_legacy_findings_only_shape(tmp_path):
    """旧形态（裸 findings 数组/代码围栏）数字降级为空，不炸。"""
    findings, numbers = visual_scan._parse_vlm_output(_VLM_JSON)
    assert len(findings) == 3  # 归一（缺 issue 丢弃）由 _normalize 处理，此处透传
    assert numbers == []


# ---------- conflict_resolve 合入 ----------


def test_conflict_resolve_merges_vlm_findings():
    state = {
        "rule_hits": [],
        "llm_findings": [],
        "vlm_findings": [
            {
                "issue": "收益数字放大",
                "reason": "红字 72px",
                "original_text": "预期年化收益率 5.8%",
                "severity": "high",
                "confidence": 0.9,
                "suggestion": "统一字号",
                "page": 1,
            }
        ],
    }
    merged = conflict_resolve(state)["merged_findings"]
    assert len(merged) == 1
    item = merged[0]
    assert item["source"] == "vlm"
    assert item["violation_type"] == "vlm"
    assert item["type"] == "禁止性"  # severity 推导与规则路同口径
    assert item["flag"] == "视觉关注"
    assert item["evidence_supported"] is None
    assert item["suggestion"] == "统一字号"


# ---------- 分流与呈现 ----------


def test_auto_confirm_never_confirms_vlm():
    """视觉判断永不自动确认（含 loose 放宽后也不确认）。"""
    loose = {"enabled": True, "threshold": 0.6}
    status, _, _ = _auto_confirm({"violation_type": "vlm", "confidence": 0.99}, loose)
    assert status == "pending_confirm"


def test_report_pending_list_flags_vlm():
    finding = {
        "violation_type": "vlm",
        "source": "vlm",
        "rule_name": "收益数字放大",
        "original_text": "预期年化收益率 5.8%",
        "risk_level": "high",
        "severity": "high",
        "page": 1,
    }
    report = build_report(1, "海报.png", "banking", [finding])
    pending = report["pending_verification"]
    assert len(pending) == 1
    assert "视觉层判断" in pending[0]["reasons"][0]
    md = render_markdown(report)
    assert "视觉模型" in md
    assert "待人工核验清单" in md


def test_vlm_model_setting_default():
    assert settings.vlm_model == "qwen-vl-plus"
    assert settings.vlm_enabled is True
