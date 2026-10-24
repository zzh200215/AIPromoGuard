"""深查通道测试（第 4 批：复杂度分级 + 受限多工具 ReAct）——全离线。

覆盖：
- 分级路由（classify._scan_intensity）：纯口号→light、含风险词短文→standard
  （变体集安全性：保义改写永远进不了 light）、长文档→deep（需 deep_scan 开）；
- 工具箱：get_document_context 跨块取证（同文档段落定位）、search_precedents
  包装、deep_tool_config 的 4 工具注册与执行分发、deep_tool_budget 覆盖值；
- llm_scan 通道分发：light 跳过 LLM、deep 注入工具箱与预算（打桩 LLM 捕获参数）。

配置打桩说明：settings 是 pydantic 模型（不可 setattr 方法），按模块替换
settings 引用为 SimpleNamespace 桩——只影响被测模块，零全局污染。
"""

import json
from types import SimpleNamespace

import pytest
from src.core.agents.nodes import classify as classify_mod
from src.core.agents.nodes import llm_scan as scan_mod
from src.core.llm import deep_tools


def _install_settings(monkeypatch, workflow: dict, modules=()):
    """给指定模块换 settings 桩（workflow 段可覆盖；其余段返回空 dict）。"""
    real = __import__("src.utils.config", fromlist=["settings"]).settings

    def app_config(section):
        if section == "workflow":
            return dict(workflow)
        if section == "llm":
            return {"tool_calling": {"enabled": False}}
        return real.app_config(section)

    stub = SimpleNamespace(app_config=app_config)
    for mod in modules:
        monkeypatch.setattr(mod, "settings", stub)


@pytest.fixture()
def base_workflow():
    """与 app.yaml 缺省一致的基线（分级开、deep 关）。"""
    return {
        "scan_intensity": True,
        "light_max_chars": 120,
        "deep_scan": False,
        "deep_min_chars": 3000,
        "deep_min_blocks": 40,
        "deep_tool_rounds": 6,
        "deep_tool_calls": 8,
        "precedent_memory": True,
        "precedent_top_k": 3,
    }


def _blocks(spec: list[str]) -> list[dict]:
    return [
        {"text": t, "page": i + 1, "paragraph": i + 1} for i, t in enumerate(spec)
    ]


# ---------- 分级路由 ----------

def test_slogan_routes_light(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (classify_mod,))
    text = "让金融更美好"
    assert classify_mod._scan_intensity(text, _blocks([text])) == "light"


def test_short_risky_text_never_light(monkeypatch, base_workflow):
    """保义改写安全性：含风险信号词的短文本必须走 standard（LLM 语义审查）。"""
    _install_settings(monkeypatch, base_workflow, (classify_mod,))
    text = "您的本金也毫发无损，到期必然分文不少地回到账户"
    assert classify_mod._scan_intensity(text, _blocks([text])) == "standard"


def test_long_doc_routes_deep_only_when_enabled(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (classify_mod,))
    blocks = _blocks([f"第{i}段产品说明内容" for i in range(50)])
    text = "".join(b["text"] for b in blocks)
    # deep_scan 关（缺省）→ 长文档仍 standard
    assert classify_mod._scan_intensity(text, blocks) == "standard"
    # deep_scan 开 → deep
    wf = {**base_workflow, "deep_scan": True}
    _install_settings(monkeypatch, wf, (classify_mod,))
    assert classify_mod._scan_intensity(text, blocks) == "deep"


def test_intensity_disabled_forces_standard(monkeypatch, base_workflow):
    _install_settings(monkeypatch, {**base_workflow, "scan_intensity": False}, (classify_mod,))
    assert classify_mod._scan_intensity("让金融更美好", _blocks(["让金融更美好"])) == "standard"


# ---------- 工具箱 ----------

def test_get_document_context_cross_block_retrieval():
    """跨块取证：A 块收益承诺 → 按探针定位 B 块风险提示段。"""
    blocks = _blocks([
        "本产品历史年化收益率 6.8%，业绩表现出色",
        "让金融更美好，选择我们",
        "风险提示：基金投资需谨慎，过往业绩不代表未来表现，市场有风险",
    ])
    out = deep_tools.get_document_context(blocks, probe="风险提示 过往业绩", max_blocks=1)
    assert out["blocks"], "应定位到风险提示段"
    assert "过往业绩不代表未来表现" in out["blocks"][0]["excerpt"]
    assert out["blocks"][0]["paragraph"] == 3


def test_get_document_context_empty_probe():
    assert deep_tools.get_document_context(_blocks(["任意"]), probe="") == {"blocks": []}


def test_search_precedents_wraps_recall(monkeypatch):
    from src.services import precedent_memory as pm

    monkeypatch.setattr(
        pm, "recall_precedents",
        lambda query, domain=None, top_k=3, **kw: [
            {"verdict": "confirmed", "original_text": "保本保收益",
             "rule_name": "禁止承诺保本保收益", "issue": "", "domain": None,
             "document_name": None, "score": 0.9},
        ],
    )
    out = deep_tools.search_precedents("保本")
    assert out["precedents"][0]["verdict"] == "人工确认违规"
    assert out["precedents"][0]["original_text"] == "保本保收益"


def test_search_penalty_cases_degrades_to_empty(monkeypatch):
    """向量库故障 → 空结果（工具失败不中断审查）。"""

    class _Boom:
        def embed(self, texts):
            raise RuntimeError("embedder down")


    monkeypatch.setattr(
        "src.infrastructure.embedding.get_embedder", lambda: _Boom()
    )
    import src.core.llm.deep_tools as dt

    monkeypatch.setattr(dt, "get_embedder", lambda: _Boom(), raising=False)
    # deep_tools 内部函数级导入：直接打桩模块导入源
    out = dt.search_penalty_cases("保本")
    assert out == {"cases": []}


def test_deep_tool_config_registers_four_tools(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (deep_tools,))
    schemas, execute = deep_tools.deep_tool_config(_blocks(["示例块"]))
    names = [s["function"]["name"] for s in schemas]
    assert names == [
        "search_regulations", "search_penalty_cases",
        "search_precedents", "get_document_context",
    ]
    out = execute("get_document_context", json.dumps({"probe": "示例"}))
    assert isinstance(out, dict)
    assert "未知工具" in execute("nope", "{}")


def test_deep_tool_budget_overrides_defaults(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (deep_tools,))
    budget = deep_tools.deep_tool_budget()
    assert budget == {"max_tool_rounds": 6, "max_tool_calls_total": 8}


# ---------- llm_scan 通道分发 ----------

class _CaptureLLM:
    model = "cap"

    def __init__(self):
        self.calls = []

    async def achat_json(self, messages, temperature=None, **kwargs):
        self.calls.append(kwargs)
        return (
            [{"issue": "x", "original_text": "y", "regulation": "z", "confidence": 0.9}],
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            [],
        )


def test_llm_scan_light_skips_llm(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (scan_mod,))
    fake = _CaptureLLM()
    monkeypatch.setattr(scan_mod, "get_llm", lambda: fake)
    out = scan_mod.llm_scan(
        {"text": "让金融更美好", "blocks": _blocks(["让金融更美好"]),
         "scan_intensity": "light", "matched_articles": []}
    )
    assert out["llm_findings"] == [] and out["llm_usage"] is None
    assert out["scan_meta"] == {"channel": "light", "skipped": "light"}
    assert fake.calls == []  # 零 LLM 调用


def test_llm_scan_deep_injects_tools_and_budget(monkeypatch, base_workflow):
    wf = {**base_workflow, "deep_scan": True}
    _install_settings(monkeypatch, wf, (scan_mod, deep_tools))
    # 关闭先例召回（本用例聚焦工具箱注入；recall 单测另有覆盖）
    monkeypatch.setattr(scan_mod, "recall_precedents", lambda *a, **kw: [])
    fake = _CaptureLLM()
    monkeypatch.setattr(scan_mod, "get_llm", lambda: fake)
    out = scan_mod.llm_scan(
        {"task_id": 1, "text": "长文档", "blocks": _blocks(["长文档内容若干"] * 3),
         "scan_intensity": "deep", "matched_articles": []}
    )
    assert out["scan_meta"]["channel"] == "deep"
    assert fake.calls, "深查通道应发起 LLM 调用"
    kw = fake.calls[0]
    assert kw.get("tools") and len(kw["tools"]) == 4
    assert kw.get("tool_budget") == {"max_tool_rounds": 6, "max_tool_calls_total": 8}
    assert callable(kw.get("execute_tool"))


def test_llm_scan_standard_no_injected_tools(monkeypatch, base_workflow):
    _install_settings(monkeypatch, base_workflow, (scan_mod,))
    monkeypatch.setattr(scan_mod, "recall_precedents", lambda *a, **kw: [])
    fake = _CaptureLLM()
    monkeypatch.setattr(scan_mod, "get_llm", lambda: fake)
    scan_mod.llm_scan(
        {"task_id": 1, "text": "常规文本", "blocks": _blocks(["常规营销文本"] * 2),
         "scan_intensity": "standard", "matched_articles": []}
    )
    kw = fake.calls[0]
    assert "tools" not in kw and "tool_budget" not in kw
