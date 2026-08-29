"""Agentic RAG 检索补检循环的纯逻辑单测（离线：FakeLLM + 桩检索，不连库/不调真 LLM）。

覆盖：
- 充分性判定 JSON 的宽容解析（围栏/杂质/截断）
- agent 循环：充分即停 / 不充分补检融合 / 无新增条款收敛 / 轮次上限 / LLM 失败降级
- regulation_match 节点：agentic 开关、llm 缺省跳过、失败保留基础召回
"""

import json
from types import SimpleNamespace

import src.core.agents.nodes.regulation_match as rm_node
from src.services import agentic_retrieval, regulation_service


def _verdict(sufficient, queries=(), reason="ok"):
    payload = {"sufficient": sufficient, "reason": reason, "follow_up_queries": list(queries)}
    usage = {"total_tokens": 10}
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), usage=usage)


class FakeLLM:
    """按脚本依次返回 complete() 结果；记录调用次数。"""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self.results.pop(0)


def _article(aid, reg="互联网保险业务监管办法", score=0.8):
    return {
        "article_id": aid,
        "regulation_id": 5,
        "regulation_name": reg,
        "article_no": "第二条",
        "content": "不得保本保收益",
        "status": "effective",
        "score": score,
    }


class _FakeDB:
    def close(self):
        pass


# ---------- parse_verdict ----------


def test_parse_verdict_variants():
    ok = '{"sufficient": false, "reason": "缺风险揭示条款", "follow_up_queries": ["风险提示义务"]}'
    assert agentic_retrieval.parse_verdict(ok) == {
        "sufficient": False,
        "reason": "缺风险揭示条款",
        "follow_up_queries": ["风险提示义务"],
    }
    fenced = "```json\n" + ok + "\n```"
    assert agentic_retrieval.parse_verdict(fenced)["sufficient"] is False
    noisy = "评估结果如下：\n" + ok + "\n以上。"
    assert agentic_retrieval.parse_verdict(noisy)["follow_up_queries"] == ["风险提示义务"]
    assert agentic_retrieval.parse_verdict("不是 JSON") is None
    assert agentic_retrieval.parse_verdict("") is None
    # 查询数截断 + 非法类型
    capped = '{"sufficient": false, "follow_up_queries": ["a", "b", "c", "d"]}'
    assert len(agentic_retrieval.parse_verdict(capped)["follow_up_queries"]) == 2
    bad = '{"sufficient": true, "follow_up_queries": "不是列表"}'
    assert agentic_retrieval.parse_verdict(bad)["follow_up_queries"] == []


# ---------- agentic_refine ----------


def test_refine_sufficient_stops_immediately(monkeypatch):
    """判定充分 → 不补检、原样返回基础召回，记录 token 用量。"""
    called = {"search": 0}

    def spy_search(*a, **k):
        called["search"] += 1
        return []

    monkeypatch.setattr(regulation_service, "search_hybrid", spy_search)
    llm = FakeLLM([_verdict(True, reason="主题已覆盖")])
    base = [_article(1), _article(2)]
    out, meta = agentic_retrieval.agentic_refine(_FakeDB(), llm, "文本", "insurance", base, 5)

    assert out == base
    assert llm.calls == 1 and called["search"] == 0
    assert meta["rounds"] == 1 and meta["sufficient"] is True and meta["added"] == 0
    assert meta["usage"]["total_tokens"] == 10


def test_refine_insufficient_runs_follow_ups(monkeypatch):
    """不充分 → 按补检查询再检索，新条款 RRF 融合进入结果。"""
    monkeypatch.setattr(
        regulation_service,
        "search_hybrid",
        lambda db, q, domain, top_k: (
            [_article(99, reg="基金销售管理办法")] if "适当性" in q else []
        ),
    )
    llm = FakeLLM([_verdict(False, ["销售适当性管理", "风险揭示"], reason="缺适当性主题")])
    base = [_article(1)]
    out, meta = agentic_retrieval.agentic_refine(_FakeDB(), llm, "文本", "fund", base, 5)

    ids = [a["article_id"] for a in out]
    assert 99 in ids and 1 in ids
    assert meta["added"] == 1 and meta["rounds"] == 2
    assert meta["queries"] == ["销售适当性管理", "风险揭示"]
    assert meta["sufficient"] is False


def test_refine_stops_when_no_new_articles(monkeypatch):
    """补检只召回重复条款 → 不融合，立即收敛。"""
    monkeypatch.setattr(
        regulation_service, "search_hybrid", lambda *a, **k: [_article(1)]
    )
    llm = FakeLLM([_verdict(False, ["相同主题"], reason="仍不充分")])
    base = [_article(1)]
    out, meta = agentic_retrieval.agentic_refine(_FakeDB(), llm, "文本", None, base, 5)

    assert out == base
    assert meta["added"] == 0 and meta["rounds"] == 1
    assert meta["queries"] == ["相同主题"]


def test_refine_respects_max_rounds(monkeypatch):
    """max_rounds=1 → 循环体不执行，零 LLM 调用。"""
    llm = FakeLLM([_verdict(False, ["x"])])
    out, meta = agentic_retrieval.agentic_refine(
        _FakeDB(), llm, "文本", None, [_article(1)], 5, max_rounds=1
    )
    assert llm.calls == 0
    assert meta["rounds"] == 1


def test_refine_unparseable_output_degrades(monkeypatch):
    """两次输出都无法解析 → 保留基础召回，sufficient=None。"""
    llm = FakeLLM(
        [SimpleNamespace(content="抱歉我不会", usage={"total_tokens": 3})] * 2
    )
    base = [_article(1)]
    out, meta = agentic_retrieval.agentic_refine(_FakeDB(), llm, "文本", None, base, 5)

    assert out == base
    assert meta["sufficient"] is None
    assert meta["usage"]["total_tokens"] == 6  # 两次调用的 token 累计


def test_refine_llm_error_degrades():
    """LLM 调用抛异常 → 原样返回基础召回，不向上抛。"""

    class BoomLLM:
        def complete(self, messages):
            raise RuntimeError("network down")

    base = [_article(1)]
    out, meta = agentic_retrieval.agentic_refine(_FakeDB(), BoomLLM(), "文本", None, base, 5)
    assert out == base
    assert meta["sufficient"] is None


# ---------- regulation_match 节点 ----------


def _patch_node(monkeypatch, articles, llm=None, workflow_cfg=None):
    monkeypatch.setattr(rm_node, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(
        regulation_service, "search_hybrid", lambda *a, **k: list(articles)
    )
    monkeypatch.setattr(rm_node, "get_llm", lambda: llm)
    cfg = {"regulation_top_k": 5, "graph_recall": False}
    cfg.update(workflow_cfg or {})
    monkeypatch.setattr(rm_node, "settings", SimpleNamespace(app_config=lambda key: cfg))


def test_node_agentic_disabled_by_default(monkeypatch):
    """缺省配置（agentic_retrieval 缺省关）→ 不触碰 LLM，行为与 P2 一致。"""
    called = {"llm": 0}

    def spy_llm():
        called["llm"] += 1
        return None

    _patch_node(monkeypatch, [_article(1)], workflow_cfg={})
    monkeypatch.setattr(rm_node, "get_llm", spy_llm)
    state = rm_node.regulation_match({"text": "文本", "domain": None})

    assert called["llm"] == 0
    assert [a["article_id"] for a in state["matched_articles"]] == [1]
    assert state["retrieval_meta"] == {}


def test_node_agentic_enabled_refines(monkeypatch):
    """显式开启 → agentic_refine 参与并回传 retrieval_meta。"""
    _patch_node(
        monkeypatch,
        [_article(1)],
        llm=FakeLLM([_verdict(True)]),
        workflow_cfg={"agentic_retrieval": True},
    )
    state = rm_node.regulation_match({"text": "文本", "domain": "fund"})

    assert state["matched_articles"][0]["article_id"] == 1
    assert state["retrieval_meta"]["rounds"] == 1
    assert state["retrieval_meta"]["sufficient"] is True
    assert state["retrieval_meta"]["usage"]["total_tokens"] == 10


def test_node_agentic_llm_absent_skips(monkeypatch):
    """开启但未配置 key（get_llm→None）→ 静默跳过，meta 为空。"""
    _patch_node(
        monkeypatch, [_article(1)], llm=None, workflow_cfg={"agentic_retrieval": True}
    )
    state = rm_node.regulation_match({"text": "文本", "domain": None})
    assert state["retrieval_meta"] == {}
    assert state["matched_articles"][0]["article_id"] == 1


def test_node_agentic_failure_keeps_base(monkeypatch):
    """agentic_refine 抛异常 → 保留基础召回，meta 清空。"""
    _patch_node(
        monkeypatch,
        [_article(1)],
        llm=FakeLLM([_verdict(True)]),
        workflow_cfg={"agentic_retrieval": True},
    )

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(agentic_retrieval, "agentic_refine", boom)
    state = rm_node.regulation_match({"text": "文本", "domain": None})

    assert [a["article_id"] for a in state["matched_articles"]] == [1]
    assert state["retrieval_meta"] == {}


def test_fuse_route_lists_effective_first_and_top_k():
    effective = _article(1)
    expired = _article(2, score=0.99)
    expired["status"] = "expired"
    out = regulation_service.fuse_route_lists([[expired], [effective]], top_k=2)
    assert [a["article_id"] for a in out] == [1, 2]  # 生效法规优先于高分失效法规
