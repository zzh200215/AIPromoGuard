"""批次/对比字段迁移测试：验证新表与新列存在、ReviewBatch 可 CRUD。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.api.main import app
from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewBatch

client = TestClient(app)


def _db_ready() -> bool:
    try:
        from src.infrastructure.database.mysql import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_tasks_has_new_columns():
    db = SessionLocal()
    rows = db.execute(text("SHOW COLUMNS FROM review_tasks LIKE 'batch_id'")).fetchall()
    db.close()
    assert len(rows) == 1


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_review_batch_crud():
    db = SessionLocal()
    b = ReviewBatch(batch_name="迁移测试批次", total_count=2)
    db.add(b)
    db.commit()
    db.refresh(b)
    assert b.id and b.status == "running"
    fetched = db.get(ReviewBatch, b.id)
    assert fetched.batch_name == "迁移测试批次"
    db.delete(b)
    db.commit()
    db.close()
