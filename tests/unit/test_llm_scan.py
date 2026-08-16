"""LLM 审查输出校验（幻觉抑制）与并发审查单元测试。"""

import src.core.agents.nodes.llm_scan as mod

_BLOCK = {"text": "本产品保本保收益", "page": 1, "paragraph": 2}


def _finding(**overrides):
    base = {
        "type": "禁止性",
        "issue": "承诺保本保收益",
        "original_text": "保本保收益",
        "regulation": "《商业银行理财业务监督管理办法》第二十六条",
        "reason": "违反禁止性规定",
        "suggestion": "删除该表述",
        "severity": "high",
        "confidence": 0.95,
    }
    base.update(overrides)
    return base


class _FakeLLM:
    """llm_scan 并发路径的假客户端：逐块返回一条合法判定，指定序号抛错。"""

    model = "fake-model"

    def __init__(self, fail_at: set[int] | None = None):
        self.calls = 0
        self.fail_at = fail_at or set()

    async def achat_json(self, messages, temperature=None):
        self.calls += 1
        if self.calls in self.fail_at:
            raise RuntimeError("LLM 调用失败")
        block_text = messages[-1]["content"].split("待审查文档片段：")[-1].strip()
        finding = _finding(issue=block_text[:20], original_text=block_text)
        return [finding], {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def _blocks(n: int) -> list[dict]:
    return [
        {"text": f"第{i}段营销表述，收益有保障", "page": 1, "paragraph": i}
        for i in range(1, n + 1)
    ]


def test_valid_finding_passes():
    valid = mod._validate_finding(_finding(), _BLOCK)
    assert valid is not None
    assert valid["type"] == "禁止性"
    assert valid["paragraph"] == 2


def test_missing_regulation_dropped():
    # 幻觉抑制：无法规依据的判定丢弃
    assert mod._validate_finding(_finding(regulation=""), _BLOCK) is None
    assert mod._validate_finding(_finding(original_text=""), _BLOCK) is None
    assert mod._validate_finding(_finding(issue=""), _BLOCK) is None


def test_low_confidence_dropped():
    assert mod._validate_finding(_finding(confidence=0.3), _BLOCK) is None


def test_invalid_enum_defaulted():
    valid = mod._validate_finding(
        _finding(type="乱七八糟", severity="critical", confidence="高"), _BLOCK
    )
    assert valid["type"] == "披露性"
    assert valid["severity"] == "medium"
    assert valid["confidence"] == 0.5


def test_confidence_clamped():
    valid = mod._validate_finding(_finding(confidence=1.5), _BLOCK)
    assert valid["confidence"] == 1.0


def test_parse_raw_strips_code_fence():
    data = mod._parse_raw('```json\n[{"issue": "x", "original_text": "y", "regulation": "z"}]\n```')
    assert len(data) == 1
    assert mod._parse_raw("not json") == []


def test_parse_raw_accepts_findings_wrapper():
    # 结构化输出契约：{"findings": [...]}（json_object 模式只允许顶层对象）
    data = mod._parse_raw('{"findings": [{"issue": "x", "original_text": "y", "regulation": "z"}]}')
    assert len(data) == 1


def test_review_prompt_contains_compliant_disclosure_whitelist():
    """W 新增：prompt 白名单指明合规披露语句（业绩比较基准/风险提示等）不判违规。"""
    from src.core.llm.prompts.review import REVIEW_SYSTEM
    assert "业绩比较基准" in REVIEW_SYSTEM
    assert "不构成收益承诺" in REVIEW_SYSTEM
    assert "过往业绩不代表未来表现" in REVIEW_SYSTEM
    assert "风险提示详见说明书" in REVIEW_SYSTEM
    assert "业绩比较基准设定的合理性" in REVIEW_SYSTEM  # 审查边界：不评价产品设计
    assert '"findings"' in REVIEW_SYSTEM  # 结构化输出契约


def test_llm_scan_degrades_without_key(monkeypatch):
    import src.core.agents.nodes.llm_scan as mod

    monkeypatch.setattr(mod, "get_llm", lambda: None)
    state = {"blocks": [{"text": "保本", "page": 1, "paragraph": 1}], "matched_articles": []}
    result = mod.llm_scan(state)
    assert result["llm_findings"] == []
    assert result["llm_usage"] is None


def test_llm_scan_reviews_all_blocks_no_truncation(monkeypatch):
    """全部块参与审查：不再有早期版本只审前 5 块的静默截断。"""
    fake = _FakeLLM()
    monkeypatch.setattr(mod, "get_llm", lambda: fake)
    state = {"blocks": _blocks(8), "matched_articles": []}
    result = mod.llm_scan(state)
    assert fake.calls == 8
    assert len(result["llm_findings"]) == 8
    usage = result["llm_usage"]
    assert usage["calls"] == 8
    assert usage["total_tokens"] == 8 * 15
    assert usage["failed_blocks"] == 0


def test_llm_scan_single_block_failure_degrades(monkeypatch):
    """单块调用失败不影响其余块，failed_blocks 计数进 usage。"""
    fake = _FakeLLM(fail_at={2})
    monkeypatch.setattr(mod, "get_llm", lambda: fake)
    state = {"blocks": _blocks(5), "matched_articles": []}
    result = mod.llm_scan(state)
    assert len(result["llm_findings"]) == 4
    assert result["llm_usage"]["failed_blocks"] == 1
    assert result["llm_usage"]["calls"] == 4  # 失败块无 usage，不计数


def test_llm_scan_respects_explicit_max_chunks(monkeypatch):
    """llm_max_chunks > 0 时作为显式成本护栏截断（默认 0 = 全审）。"""
    from types import SimpleNamespace

    fake = _FakeLLM()
    monkeypatch.setattr(mod, "get_llm", lambda: fake)
    monkeypatch.setattr(
        mod,
        "settings",
        SimpleNamespace(
            app_config=lambda section: (
                {
                    "llm_max_chunks": 3,
                    "llm_concurrency": 2,
                    "llm_confidence_threshold": 0.5,
                }
                if section == "workflow"
                else {}
            )
        ),
    )
    state = {"blocks": _blocks(5), "matched_articles": []}
    result = mod.llm_scan(state)
    assert fake.calls == 3
    assert len(result["llm_findings"]) == 3


def test_llm_scan_skips_empty_blocks(monkeypatch):
    fake = _FakeLLM()
    monkeypatch.setattr(mod, "get_llm", lambda: fake)
    state = {
        "blocks": [{"text": "  ", "page": 1, "paragraph": 1}] + _blocks(2),
        "matched_articles": [],
    }
    mod.llm_scan(state)
    assert fake.calls == 2  # 空白块不发起 LLM 调用
