"""检索层排除"已废止/演示"数据的护栏。

背景（2026-10-22）：演示法规《证券投资基金销售宣传合规管理规定（演示）》状态为
effective、且进了向量库，在"承诺保本高收益"这类核心查询里排 **Top-1（d=0.373）**，
会被当成审查依据写进报告。合规产品引用一条演示法规是硬伤。

处理：状态置 deprecated，检索层（语义 + 关键词）统一排除，且**排除后仍要凑满 top_k**
——先多取候选再截断，否则会白白少一条召回。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.services.regulation_service as rs  # noqa: E402


def _hit(i: int, status: str, name: str = "某办法") -> dict:
    return {
        "id": str(i),
        "score": round(1 - i * 0.01, 4),
        "document": f"第{i}条 内容",
        "metadata": {
            "article_id": i,
            "regulation_id": 100 + i,
            "regulation_name": f"{name}{i}",
            "article_no": f"第{i}条",
            "status": status,
        },
    }


class _FakeStore:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def query(self, collection, vec, top_k=10, where=None):
        self.calls.append(top_k)
        return self.hits[:top_k]


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3]]


def test_semantic_filters_deprecated(monkeypatch):
    store = _FakeStore(
        [_hit(0, "deprecated", "演示办法"), _hit(1, "effective"), _hit(2, "effective")]
    )
    monkeypatch.setattr(rs, "get_vector_store", lambda: store)
    monkeypatch.setattr(rs, "get_embedder", lambda: _FakeEmbedder())
    out = rs.search_semantic("保本保收益", None, 2)
    assert [x["regulation_name"] for x in out] == ["某办法1", "某办法2"]


def test_semantic_still_returns_top_k_after_filter(monkeypatch):
    """被过滤掉一条后，仍要靠多取候选凑满 top_k。"""
    hits = [
        _hit(0, "deprecated"),
        _hit(1, "effective"),
        _hit(2, "effective"),
        _hit(3, "effective"),
    ]
    store = _FakeStore(hits)
    monkeypatch.setattr(rs, "get_vector_store", lambda: store)
    monkeypatch.setattr(rs, "get_embedder", lambda: _FakeEmbedder())
    out = rs.search_semantic("x", None, 3)
    assert len(out) == 3
    assert all(x["status"] == "effective" for x in out)
    # 上游必须多取（top_k + 5），否则过滤后会缺额
    assert store.calls[0] == 8


def test_semantic_keeps_status_field(monkeypatch):
    store = _FakeStore([_hit(1, "effective")])
    monkeypatch.setattr(rs, "get_vector_store", lambda: store)
    monkeypatch.setattr(rs, "get_embedder", lambda: _FakeEmbedder())
    out = rs.search_semantic("x", None, 1)
    assert out[0]["status"] == "effective"
