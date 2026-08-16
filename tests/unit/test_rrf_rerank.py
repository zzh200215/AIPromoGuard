"""混合检索融合单元测试：RRF 融合、生效法规优先、可选 rerank。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services import regulation_service as svc


def _item(aid: int, score: float, status: str = "effective", name: str = "某办法") -> dict:
    return {
        "article_id": aid,
        "regulation_id": aid * 10,
        "regulation_name": name,
        "article_no": f"第{aid}条",
        "content": f"条款{aid}",
        "status": status,
        "score": score,
        "highlight": "",
    }


# ---- _rrf_fuse 纯函数 ----


def test_rrf_prefers_dual_route_hits():
    """双路都命中的条款排名应高于单路第一（RRF 分数叠加）。"""
    semantic = [_item(1, 0.95), _item(2, 0.90), _item(3, 0.85)]
    keyword = [_item(2, 2.1), _item(4, 1.0)]  # 语义分 0-1、关键词分可 >1：量纲不统一
    fused = svc._rrf_fuse([semantic, keyword])
    ids = [f["article_id"] for f in fused]
    assert ids[0] == 2  # 两路都命中且都排前列 → 融合分最高
    assert set(ids) == {1, 2, 3, 4}
    # 归一化到 0-1
    assert all(0.0 <= f["rrf_score"] <= 1.0 for f in fused)
    assert fused[0]["score"] == fused[0]["rrf_score"]


def test_rrf_dedupes_by_article_id():
    semantic = [_item(1, 0.9)]
    keyword = [_item(1, 1.5)]
    fused = svc._rrf_fuse([semantic, keyword])
    assert len(fused) == 1
    # 字段保留原始分更高的一路（keyword 1.5 的痕迹通过融合体现，字段本身二选一）
    assert fused[0]["article_id"] == 1


def test_rrf_empty_inputs():
    assert svc._rrf_fuse([[], []]) == []


def test_normalize_constant_sequence():
    assert svc._normalize([0.5, 0.5]) == [1.0, 1.0]
    assert svc._normalize([0.0, 1.0]) == [0.0, 1.0]


# ---- search_hybrid 集成（monkeypatch 两路检索） ----


def _patch_routes(monkeypatch, semantic, keyword):
    monkeypatch.setattr(svc, "search_semantic", lambda *a, **k: semantic)
    monkeypatch.setattr(svc, "search_keyword", lambda *a, **k: keyword)


def test_search_hybrid_effective_regulations_first(monkeypatch):
    """RRR 融合后，生效法规仍优先于废止法规（即使废止条款融合分更高）。"""
    semantic = [_item(9, 0.99, status="repealed")]
    keyword = [_item(9, 2.5, status="repealed"), _item(1, 0.5)]
    _patch_routes(monkeypatch, semantic, keyword)
    results = svc.search_hybrid(db=None, query="q", domain=None, top_k=5)
    assert results[0]["status"] == "effective"
    assert results[0]["article_id"] == 1


def test_search_hybrid_rerank_disabled_by_default(monkeypatch):
    """rerank 默认关闭：不触发模型加载，排序保持 RRF。"""
    semantic = [_item(1, 0.9), _item(2, 0.8)]
    keyword = [_item(2, 1.2)]
    _patch_routes(monkeypatch, semantic, keyword)
    loaded = {"n": 0}

    def _boom_init(*a, **k):
        loaded["n"] += 1
        raise RuntimeError("不应加载 rerank 模型")

    import src.services.regulation_service as mod

    monkeypatch.setattr(mod, "_reranker", None)
    monkeypatch.setattr(mod, "_reranker_failed", False)
    monkeypatch.setattr(
        "fastembed.rerank.cross_encoder.TextCrossEncoder", _boom_init, raising=False
    )
    results = svc.search_hybrid(db=None, query="q", domain=None, top_k=5)
    assert loaded["n"] == 0
    assert [r["article_id"] for r in results][0] == 2  # 双路命中者居首


def test_search_hybrid_rerank_reorders_when_enabled(monkeypatch):
    """启用 rerank 且模型就绪时：final = w*rerank_norm + (1-w)*rrf。"""
    semantic = [_item(1, 0.9), _item(2, 0.8)]
    keyword = [_item(2, 1.2)]
    _patch_routes(monkeypatch, semantic, keyword)

    fake_reranker = MagicMock()
    # RRF 顺序为 [2, 1]；rerank 给 article 1 最高分（0.99）：顺序应被重排为 1 在前
    fake_reranker.rerank.return_value = [0.01, 0.99]
    monkeypatch.setattr(svc, "_reranker", fake_reranker)
    monkeypatch.setattr(svc, "_reranker_failed", False)
    # Settings 是 pydantic 模型不可 setattr 非字段，整体替换模块内 settings 引用
    monkeypatch.setattr(
        svc,
        "settings",
        SimpleNamespace(
            app_config=lambda section: (
                {"rerank": {"enabled": True, "model": "x", "weight": 0.7}}
                if section == "vectorstore"
                else {"fallback_models": []}
            )
        ),
    )
    results = svc.search_hybrid(db=None, query="q", domain=None, top_k=5)
    assert results[0]["article_id"] == 1
    assert "rerank_score" in results[0]
    assert results[0]["score"] != results[0]["rrf_score"]  # 已融合


def test_search_hybrid_rerank_failure_falls_back(monkeypatch):
    """rerank 调用失败：回退 RRF 排序，不抛错。"""
    semantic = [_item(1, 0.9), _item(2, 0.8)]
    keyword = []
    _patch_routes(monkeypatch, semantic, keyword)

    fake_reranker = MagicMock()
    fake_reranker.rerank.side_effect = RuntimeError("rerank boom")
    monkeypatch.setattr(svc, "_reranker", fake_reranker)
    monkeypatch.setattr(svc, "_reranker_failed", False)
    monkeypatch.setattr(
        svc,
        "settings",
        SimpleNamespace(
            app_config=lambda section: (
                {"rerank": {"enabled": True, "weight": 0.7}}
                if section == "vectorstore"
                else {"fallback_models": []}
            )
        ),
    )
    results = svc.search_hybrid(db=None, query="q", domain=None, top_k=5)
    assert [r["article_id"] for r in results] == [1, 2]
