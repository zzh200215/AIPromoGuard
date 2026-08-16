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
