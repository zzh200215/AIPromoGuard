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


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_keyword_search_long_document_text():
    """降级路径回归：整段文档长文本不再恒空，能按抽取关键词召回条款。"""
    db = SessionLocal()
    try:
        long_text = (
            "本理财产品由公司发行，投资须知：产品宣传不得保本保收益，"
            "过往业绩不代表未来表现，请仔细阅读产品说明书与风险揭示书。" * 8
        )
        assert len(long_text) > 200
        results = regulation_service.search_keyword(db, long_text, ["banking"], 5)
        assert len(results) > 0
        assert any("保本" in r["content"] or "理财" in r["content"] for r in results)
    finally:
        db.close()


def test_extract_keywords_filters_function_words():
    """关键词抽取：领域词入选、高频虚词被滤。"""
    from src.services.regulation_service import _extract_keywords

    text = "本理财产品保本保收益，我们可以承诺刚性兑付，预期年化收益率5.8%。" * 5
    kws = _extract_keywords(text)
    assert kws
    assert "我们" not in kws
    assert "可以" not in kws
    assert any(k in {"理财", "产品", "保本", "收益", "刚性", "兑付", "承诺"} for k in kws)


# ---------- 可验证证据链：enrich_regulation_meta ----------

class _FakeRegQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeRegDB:
    """只实现 enrich_regulation_meta 用到的 query(Regulation).filter(...).all()。"""

    def __init__(self, rows):
        self._rows = rows
        self.queries = 0

    def query(self, model):
        self.queries += 1
        return _FakeRegQuery(self._rows)


def test_enrich_regulation_meta_fills_and_idempotent():
    """补齐文号/日期；已带字段的列表不重查（幂等守卫）。"""
    from datetime import date
    from types import SimpleNamespace

    from src.services import regulation_service as rs

    reg = SimpleNamespace(
        id=7,
        regulation_no="银保监会令2021年第7号",
        publish_date=date(2021, 10, 29),
        effective_date=date(2022, 2, 1),
    )
    db = _FakeRegDB([reg])
    articles = [
        {
            "article_id": 1,
            "regulation_id": 7,
            "regulation_name": "互联网保险业务监管办法",
            "article_no": "第二十六条",
            "content": "x",
            "status": "effective",
        }
    ]
    out = rs.enrich_regulation_meta(db, articles)
    assert out[0]["regulation_no"] == "银保监会令2021年第7号"
    assert out[0]["publish_date"] == "2021-10-29"
    assert out[0]["effective_date"] == "2022-02-01"
    rs.enrich_regulation_meta(db, out)  # 已带字段 → 不再发查询
    assert db.queries == 1


def test_enrich_regulation_meta_unknown_reg_and_failure_safe():
    """向量元数据陈旧（查无此 regulation_id）→ 字段显式补 None；DB 故障静默跳过。"""
    from src.services import regulation_service as rs

    out = rs.enrich_regulation_meta(
        _FakeRegDB([]), [{"regulation_id": 999, "article_id": 1}]
    )
    assert out[0]["regulation_no"] is None
    assert out[0]["publish_date"] is None
    assert out[0]["effective_date"] is None

    class _BoomDB:
        def query(self, model):
            raise RuntimeError("db down")

    articles = [{"regulation_id": 5}]
    assert rs.enrich_regulation_meta(_BoomDB(), articles) == articles


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_hybrid_search_enriches_evidence_chain():
    """可验证证据链：混合检索结果带法规文号与发布/生效日期（缺省显式 None）。"""
    db = SessionLocal()
    try:
        results = regulation_service.search_hybrid(db, "不得承诺保本保收益", ["banking"], 5)
        assert results
        for r in results:
            assert "regulation_no" in r
            for key in ("publish_date", "effective_date"):
                assert r[key] is None or len(r[key]) == 10  # ISO 日期串或 None
    finally:
        db.close()


# ---- 同义扩展第四路（营销话术→监管术语，2026-10-24）----

def test_regulatory_synonym_terms_hit_and_dedupe():
    """触发词命中→监管术语收集（去重保序）；干净文本不触发。"""
    terms = regulation_service.regulatory_synonym_terms("本产品保本稳赚，年化收益上不封顶")
    assert terms  # 保本/稳赚/年化/上不封顶至少触发一组
    assert len(terms) == len(set(terms))
    assert any("承诺" in t or "保本" in t for t in terms)
    assert regulation_service.regulatory_synonym_terms("今天天气不错") == []


def test_regulatory_synonym_terms_cap():
    """触发面过宽时封顶 _SYNONYM_TERM_CAP（防长文把扩展路变成全库扫描）。"""
    text = ("保本 保息 稳赚 无风险 承诺 翻倍 暴涨 上不封顶 年化 业绩比较基准 "
            "限时 限量 抢购 返现 荐股 牛股")
    terms = regulation_service.regulatory_synonym_terms(text)
    assert len(terms) == regulation_service._SYNONYM_TERM_CAP


def _kb_rich(min_articles: int = 500) -> bool:
    """知识库规模护栏：映射表守护只在富库环境有效。

    fcr_test 只播 10 部法规种子（~45 条），映射目标未必在内——0 命中属种子
    覆盖问题而非映射漂移，跳过；dev 库（2951 条）与全量种子环境才执行守护。
    """
    try:
        from sqlalchemy import text as sql_text

        db = SessionLocal()
        n = db.execute(sql_text("SELECT COUNT(*) FROM articles")).scalar()
        db.close()
        return (n or 0) >= min_articles
    except Exception:
        return False


@pytest.mark.skipif(
    not (_ready() and _kb_rich()), reason="富库环境不可用（fcr_test 种子库不执行映射守护）",
)
def test_synonym_targets_hit_kb():
    """映射表防漂移守护：每个监管术语在库内必须仍有命中（否则该路白跑）。"""
    db = SessionLocal()
    try:
        all_terms = {t for terms in regulation_service.MARKETING_SYNONYMS.values() for t in terms}
        for term in sorted(all_terms):
            hits = regulation_service.search_keyword(db, term, None, 3)
            assert hits, f"同义映射目标 [{term}] 在库内 0 命中——映射表与知识库漂移"
    finally:
        db.close()


@pytest.mark.skipif(not _ready(), reason="数据库或向量库不可用")
def test_regulation_match_records_synonym_terms():
    """节点级集成：营销话术文档 → 第四路触发且 fusion 后条款非空，meta 留痕。"""
    from src.core.agents.nodes.regulation_match import regulation_match

    result = regulation_match({"text": "限时抢购！本产品保本稳赚，年化收益翻倍", "domain": "fund"})
    meta = result.get("retrieval_meta") or {}
    assert meta.get("synonym_terms"), "营销触发词在场却未记录同义扩展术语"
    assert result.get("matched_articles")
