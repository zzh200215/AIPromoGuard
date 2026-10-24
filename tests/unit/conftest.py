"""集成测试 DB 卫生（方向④）：清理测试期间新建的 review 数据。

部分 E2E 风格测试（batch / compare / review_flow）通过真实 API 建批次/任务，auto-increment
id 落在共享开发库；不清会污染 feedback 统计与规则精调建议（此前 task 233 泄漏过一条
"[复核] 测试人工复核"，正是 test_review_flow 的残留，已修）。此 autouse fixture 在每个
测试开始前记录 review_batches / review_tasks / review_results 的最大 id，结束后删除本次
新建的行——只动本测试新增、不触碰既有数据。DB 不可用时优雅跳过（DB 测试有 skipif 保护）。

注意：依赖该表在测试期间只增不删；删顺序 results → tasks → batches 满足外键依赖。
"""

import pytest
from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal
from src.models import ProductMaterial


@pytest.fixture(autouse=True)
def _isolated_precedent_vectors(tmp_path, monkeypatch):
    """先例记忆向量隔离：单测中的先例写入/召回一律落到临时 Chroma 目录。

    先例集合（legal_precedents）是真实审查的召回源——confirm 端点测试等
    任何触发 sync_after_verdict 的用例若直写 data/chroma，垃圾向量会进入
    真实审查的记忆。DB 行随 results 级联清理，但向量没有 FK，必须在此截断。
    """
    from src.infrastructure.vectorstore.chroma import ChromaVectorStore
    from src.services import precedent_memory as pm

    store = ChromaVectorStore(persist_dir=str(tmp_path / "precedents-chroma"))
    monkeypatch.setattr(pm, "get_vector_store", lambda: store)


@pytest.fixture()
def isolated_materials():
    """影响分析类测试隔离：临时归档既有在用材料台账，结束后恢复。

    _locate_materials 按产品类型圈全部 active 材料，演示种子或并行开发
    数据会污染计数断言；本夹具让测试只看见自己新建的材料。
    """
    db = SessionLocal()
    active_ids = [
        row[0]
        for row in db.query(ProductMaterial.id)
        .filter(ProductMaterial.status == "active")
        .all()
    ]
    if active_ids:
        db.query(ProductMaterial).filter(ProductMaterial.id.in_(active_ids)).update(
            {"status": "archived"}, synchronize_session=False
        )
        db.commit()
    db.close()

    yield

    db = SessionLocal()
    try:
        if active_ids:
            db.query(ProductMaterial).filter(ProductMaterial.id.in_(active_ids)).update(
                {"status": "active"}, synchronize_session=False
            )
            db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_review_data():
    try:
        db = SessionLocal()
        max_batch = db.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM review_batches")
        ).scalar()
        max_task = db.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM review_tasks")
        ).scalar()
        max_result = db.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM review_results")
        ).scalar()
        db.close()
    except Exception:
        yield  # DB 不可用：不清理
        return

    yield

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM review_results WHERE id > :m"), {"m": max_result})
        db.execute(text("DELETE FROM review_tasks WHERE id > :m"), {"m": max_task})
        db.execute(text("DELETE FROM review_batches WHERE id > :m"), {"m": max_batch})
        db.commit()
    finally:
        db.close()
