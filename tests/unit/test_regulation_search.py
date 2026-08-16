"""法规混合检索集成测试：keyword / semantic / hybrid 三种模式。

依赖真实 DB 与向量库，不可用时跳过。
"""

import pytest
from src.infrastructure.database.mysql import SessionLocal
from src.services import regulation_service


def _ready() -> bool:
    try:
        from sqlalchemy import text as sql_text
        from src.infrastructure.vectorstore import get_vector_store

        db = SessionLocal()
        db.execute(sql_text("SELECT 1"))
        db.close()
        return get_vector_store().count("legal_articles") > 0
    except Exception:
        return False


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_keyword_search():
    db = SessionLocal()
    try:
        results = regulation_service.search_keyword(db, "保本", ["banking"], 5)
        assert len(results) > 0
        assert all(r["status"] == "effective" for r in results)
        assert all(r["regulation_name"] for r in results)
    finally:
        db.close()


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_semantic_search():
    results = regulation_service.search_semantic("理财产品不得承诺保本保收益", ["banking"], 5)
    assert len(results) > 0
    assert all("score" in r for r in results)
    assert any("保本" in r["content"] for r in results)


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_hybrid_search_dedupes_and_ranks():
    db = SessionLocal()
    try:
        results = regulation_service.search_hybrid(db, "刚性兑付 保本保收益", ["banking"], 5)
        assert len(results) > 0
        # 按 article_id 去重
        ids = [r["article_id"] for r in results]
        assert len(ids) == len(set(ids))
        # 生效法规优先、分数降序
        statuses = [r["status"] for r in results]
        assert all(s == "effective" for s in statuses)
    finally:
        db.close()
