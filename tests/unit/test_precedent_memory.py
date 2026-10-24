"""判定先例记忆（第 2 批能力）测试：沉淀、召回、注入、隔离。

分层：
- 服务层（DB）：sync_after_verdict 的 upsert / 翻案覆盖 / 撤销删除 / 自动确认不沉淀；
- 召回层（无 DB）：过滤（同任务排除 / 领域优先 / verdict 合法性）、top_k、失败降级；
- 注入层（无 DB）：build_review_messages 的先例段（无先例时与历史版本逐字节一致）；
- 隔离层：tests/unit/conftest.py 的 autouse 夹具保证向量不外漏（此处验证其生效）。

Embedding 用字符袋 fake：同字重叠 → 高相似，足以驱动排序断言且零模型依赖。
"""

from datetime import datetime

import pytest
from src.core.llm.prompts.review import build_review_messages
from src.services import precedent_memory as pm
from src.services.precedent_memory import recall_precedents, sync_after_verdict

pytestmark = pytest.mark.usefixtures("_isolated_precedent_vectors")


class _FakeEmbedder:
    """字符袋向量：16 维，按字符 ord 分桶计数——同字重叠即相似。"""

    name = "fake"
    dim = 16

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 16
            for ch in t:
                v[ord(ch) % 16] += 1.0
            out.append(v)
        return out


@pytest.fixture()
def fake_embedder(monkeypatch):
    monkeypatch.setattr(pm, "get_embedder", lambda: _FakeEmbedder())
    return _FakeEmbedder()


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import ReviewResult

        db = SessionLocal()
        db.query(ReviewResult.id).limit(1).all()
        db.close()
        return True
    except Exception:
        return False


def _make_result(db, task, status="confirmed", confirmed_by=1, rule_id=None):
    from src.models import ReviewResult

    result = ReviewResult(
        task_id=task.id,
        violation_type="llm",
        risk_level="high",
        original_text="本产品保本保收益，历史年化12%",
        description="承诺保本保收益",
        status=status,
        confirmed_by=confirmed_by,
        confirmed_at=datetime.now() if confirmed_by else None,
        rule_id=rule_id,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def _make_task(db, name="先例测试材料.txt", domain="banking"):
    from src.models import ReviewTask

    task = ReviewTask(task_name=name, document_name=name, domain=domain, status="completed")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture()
def db_session():
    """直连测试库（fcr_test）的短事务会话；行清理交给 conftest 的 autouse 夹具。"""
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    yield db
    db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_sync_upsert_flip_and_revert(db_session, fake_embedder):
    """人工判定 → 沉淀；翻案 → 覆盖（仍一条）；撤销 → 删除。"""
    from src.models import ReviewPrecedent

    task = _make_task(db_session)
    result = _make_result(db_session, task, status="confirmed")

    sync_after_verdict(db_session, result)
    rows = db_session.query(ReviewPrecedent).filter_by(result_id=result.id).all()
    assert len(rows) == 1 and rows[0].verdict == "confirmed"
    assert rows[0].task_id == task.id and rows[0].domain == "banking"
    # 向量已入隔离集合
    assert pm.get_vector_store().count(pm.COLLECTION) == 1

    # 翻案：confirmed → false_positive，仍一条且 verdict 更新
    result.status = "false_positive"
    db_session.commit()
    sync_after_verdict(db_session, result)
    rows = db_session.query(ReviewPrecedent).filter_by(result_id=result.id).all()
    assert len(rows) == 1 and rows[0].verdict == "false_positive"

    # 撤销复核：pending_confirm → 先例删除（记忆等于最新人工判断）
    result.status = "pending_confirm"
    result.confirmed_by = None
    db_session.commit()
    sync_after_verdict(db_session, result)
    assert db_session.query(ReviewPrecedent).filter_by(result_id=result.id).count() == 0
    assert pm.get_vector_store().count(pm.COLLECTION) == 0


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_sync_skips_auto_confirmed(db_session, fake_embedder):
    """系统自动确认（confirmed_by=None）不沉淀——数据卫生，避免循环论证。"""
    from src.models import ReviewPrecedent

    task = _make_task(db_session, name="自动确认材料.txt")
    result = _make_result(db_session, task, status="confirmed", confirmed_by=None)
    sync_after_verdict(db_session, result)
    assert db_session.query(ReviewPrecedent).filter_by(result_id=result.id).count() == 0


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_sync_failure_does_not_raise(db_session, monkeypatch):
    """向量库故障时沉淀降级为告警——不允许阻塞人工判定主流程。"""
    task = _make_task(db_session, name="故障降级材料.txt")
    result = _make_result(db_session, task)

    def _boom():
        raise RuntimeError("vector store down")

    monkeypatch.setattr(pm, "get_embedder", _boom)
    sync_after_verdict(db_session, result)  # 不得抛异常


def _seed_vectors(store, embedder):
    """三条先例：同域误报 / 同域确认 / 跨域确认。"""
    texts = [
        ("101", "业绩比较基准不代表未来业绩表现",
         {"verdict": "false_positive", "task_id": 11, "domain": "banking"}),
        ("102", "本产品保本保收益到期稳赚",
         {"verdict": "confirmed", "task_id": 12, "domain": "banking"}),
        ("103", "本产品保本保收益跨域保险版",
         {"verdict": "confirmed", "task_id": 13, "domain": "insurance"}),
    ]
    ids = [t[0] for t in texts]
    docs = [t[1] for t in texts]
    metas = [t[2] for t in texts]
    store.add(pm.COLLECTION, ids, embedder.embed(docs), docs, metas)


def test_recall_ranks_and_filters(fake_embedder):
    """召回：同域优先于跨域、排除同任务、verdict 透传、top_k 生效。"""
    store = pm.get_vector_store()
    _seed_vectors(store, fake_embedder)

    # 查询与"业绩比较基准"高度相似（同字符重叠）→ 同域误报先例排第一
    got = recall_precedents(
        "业绩比较基准不代表未来业绩表现吗",
        domain="banking",
        top_k=3,
        exclude_task_id=99,
        store=store,
        embedder=fake_embedder,
    )
    assert got and got[0]["verdict"] == "false_positive"
    assert all(g["verdict"] in ("confirmed", "false_positive") for g in got)

    # 排除同任务：task 11 的先例被剔除后不再出现在结果
    got2 = recall_precedents(
        "业绩比较基准不代表未来业绩表现",
        domain="banking",
        top_k=3,
        exclude_task_id=11,
        store=store,
        embedder=fake_embedder,
    )
    assert all("业绩比较基准" not in (g["original_text"] or "") for g in got2)

    # top_k 截断
    got3 = recall_precedents(
        "保本保收益",
        domain="banking",
        top_k=1,
        exclude_task_id=None,
        store=store,
        embedder=fake_embedder,
    )
    assert len(got3) == 1


def test_recall_domain_preference(fake_embedder):
    """领域优先：同域先例用尽前不取跨域。"""
    store = pm.get_vector_store()
    _seed_vectors(store, fake_embedder)
    got = recall_precedents(
        "本产品保本保收益",
        domain="insurance",
        top_k=2,
        store=store,
        embedder=fake_embedder,
    )
    # insurance 域只有一条 → 结果首条应为跨域标记前的同域（保险版）
    assert got and got[0]["domain"] == "insurance"


def test_recall_failure_degrades_to_empty(fake_embedder):
    """向量库故障 → 返回 []（审查主路径零依赖）。"""

    class _BoomStore:
        def query(self, *a, **k):
            raise RuntimeError("chroma down")

    got = recall_precedents("任意文本", top_k=3, store=_BoomStore(), embedder=fake_embedder)
    assert got == []


def test_recall_disabled_returns_empty(fake_embedder, monkeypatch):
    """workflow.precedent_memory=false → 不召回（开关行为）。"""
    monkeypatch.setattr(pm, "_memory_enabled", lambda: False)
    got = recall_precedents("任意文本", top_k=3)
    assert got == []


def test_build_messages_precedent_section():
    """先例段注入位置（法规 → 先例 → 待审文本）；无先例时与历史格式逐字节一致。"""
    articles = [
        {
            "regulation_name": "资管新规",
            "article_no": "第十九条",
            "content": "不得承诺保本",
        }
    ]
    precedents = [
        {
            "verdict": "false_positive",
            "original_text": "业绩比较基准不代表未来",
            "rule_name": "禁止承诺保本保收益",
        }
    ]

    plain = build_review_messages("待审文本", articles)
    assert "历史人工判定" not in plain[1]["content"]
    assert plain[1]["content"] == (
        "相关法规条款：\n[资管新规 第十九条] 不得承诺保本\n\n待审查文档片段：\n待审文本"
    )

    with_p = build_review_messages("待审文本", articles, precedents=precedents)
    content = with_p[1]["content"]
    assert "历史人工判定" in content
    assert "人工判定合规（系统曾误报，已被人工纠正）" in content
    assert "业绩比较基准不代表未来" in content
    # 顺序：法规 → 先例 → 待审文本
    i_reg, i_prec, i_doc = (
        content.index("相关法规条款"),
        content.index("历史人工判定"),
        content.index("待审查文档片段"),
    )
    assert i_reg < i_prec < i_doc
