"""监管动态表迁移测试：表存在、ORM CRUD、UNIQUE 约束。"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.infrastructure.database.mysql import SessionLocal
from src.models import RegulationUpdate


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_regulation_updates_table_exists():
    db = SessionLocal()
    rows = db.execute(
        text(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'regulation_updates'"
        )
    ).fetchall()
    db.close()
    assert len(rows) == 1


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_regulation_update_crud():
    db = SessionLocal()
    try:
        u = RegulationUpdate(
            source="pbc",
            title="迁移测试法规",
            status="pending",
            match_type="fetch",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        assert u.id and u.status == "pending"
        fetched = db.get(RegulationUpdate, u.id)
        assert fetched.title == "迁移测试法规"
        assert fetched.matched_regulations is None
        db.delete(u)
        db.commit()
    finally:
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_unique_source_title_constraint():
    db = SessionLocal()
    try:
        db.add(RegulationUpdate(source="nfra", title="唯一迁移测试法规", status="pending"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(RegulationUpdate(source="nfra", title="唯一迁移测试法规", status="pending"))
            db.commit()
        db.rollback()
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "唯一迁移测试法规").delete()
        db.commit()
        db.close()
