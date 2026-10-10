"""ChromaVectorStore 单元测试：使用隔离的临时持久化目录，避免与运行中应用共享 data/chroma。

含 factory 守卫测试（PR-8）：Chroma 收敛为唯一实现后，合法配置返回 ChromaVectorStore、
非法配置值响亮报错（.env 残留 milvus 历史值时不得静默降级）。
"""

import uuid
from types import SimpleNamespace

import pytest
from src.infrastructure.vectorstore.chroma import ChromaVectorStore

COLLECTION = "legal_articles_test"


def test_add_query_delete_roundtrip(tmp_path):
    store = ChromaVectorStore(persist_dir=str(tmp_path / "chroma"))
    ids = [str(uuid.uuid4()) for _ in range(2)]
    try:
        store.add(
            COLLECTION,
            ids,
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
            ["不得承诺保本保收益", "净值随市场波动"],
            [{"article_id": 1}, {"article_id": 2}],
        )
        assert store.count(COLLECTION) == 2

        results = store.query(COLLECTION, [1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == ids[0]  # 最相似排最前
        assert results[0]["score"] > 0.99
        assert results[0]["metadata"]["article_id"] == 1
    finally:
        store.delete(COLLECTION, ids)
    assert store.count(COLLECTION) == 0


# ---- factory 守卫（PR-8：Milvus 死分支清理后 Chroma 为唯一实现） ----


def test_factory_returns_chroma(tmp_path, monkeypatch):
    """唯一合法配置：返回 ChromaVectorStore（隔离 tmp 目录，不碰真实 data/chroma）。

    settings 用 SimpleNamespace 整体替换模块内引用（pydantic Settings 不可 setattr）；
    lru_cache 前后都清，避免测试实例污染其他用例的缓存。
    """
    from src.infrastructure.vectorstore import chroma as chroma_mod
    from src.infrastructure.vectorstore import factory as factory_mod

    monkeypatch.setattr(
        factory_mod, "settings", SimpleNamespace(vector_store_type="chroma")
    )
    monkeypatch.setattr(
        chroma_mod, "settings", SimpleNamespace(chroma_persist_dir=str(tmp_path / "chroma"))
    )
    factory_mod.get_vector_store.cache_clear()
    try:
        store = factory_mod.get_vector_store()
        assert isinstance(store, ChromaVectorStore)
    finally:
        factory_mod.get_vector_store.cache_clear()


def test_factory_rejects_non_chroma(monkeypatch):
    """非 chroma 配置值响亮报错（.env 残留 milvus 历史值时不得静默降级）。"""
    from src.infrastructure.vectorstore import factory as factory_mod

    monkeypatch.setattr(
        factory_mod, "settings", SimpleNamespace(vector_store_type="milvus")
    )
    factory_mod.get_vector_store.cache_clear()
    try:
        with pytest.raises(ValueError, match="chroma"):
            factory_mod.get_vector_store()
    finally:
        factory_mod.get_vector_store.cache_clear()
