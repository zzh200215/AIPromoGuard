"""ChromaVectorStore 单元测试：使用隔离的临时持久化目录，避免与运行中应用共享 data/chroma。"""

import uuid

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
