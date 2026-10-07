"""时效性告警写入单测（R3-2 v2）：纯函数合并规则 + 容器幂等 + 键兼容回归.

覆盖：新增/刷新保留决策/依据恢复自动关闭/系统关闭条目自愈重开/人工驳回不受影响；
_entry_key 命名空间（stale 条目无 task_id 不再让复测回写 KeyError）。
DB 用例遵循项目约定：真实 SessionLocal + 数据库不可用自动 skip。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from src.infrastructure.database.mysql import SessionLocal
from src.models import ImpactAssessment, ReviewBatch
from src.services.impact_service import (
    STALE_CONTAINER_TITLE,
    _entry_key,
    decide_remediation,
    get_or_create_stale_container,
    merge_stale_entries,
    sync_batch_to_assessment,
)


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:  # noqa: BLE001
        return False


_db_required = pytest.mark.skipif(not _db_ready(), reason="数据库不可用")


def _stale(mid: int, name: str = "海报", reasons: list[str] | None = None) -> dict:
    return {
        "material_id": mid,
        "name": name,
        "version": "v1",
        "last_review_status": "violation",
        "reasons": reasons or [f"规则已停用：R{mid}"],
    }


# ---------- _entry_key：命名空间区分（纯函数） ----------


def test_entry_key_task_namespace():
    assert _entry_key({"task_id": 7}) == "task:7"


def test_entry_key_stale_namespace():
    assert _entry_key({"kind": "stale", "material_id": 9}) == "stale:9"


def test_entry_key_no_crash_without_task_id():
    """stale 条目无 task_id：旧实现直取 entry["task_id"] 会 KeyError。"""
    assert _entry_key({"material_id": 9}) == "stale:9"


# ---------- merge_stale_entries：合并规则（纯函数，不 skip） ----------


def test_merge_adds_new_stale():
    remediation: list[dict] = []
    counts = merge_stale_entries(remediation, [_stale(1), _stale(2)])
    assert counts == {"added": 2, "refreshed": 0, "resolved": 0, "reopened": 0}
    assert [e["material_id"] for e in remediation] == [1, 2]
    assert all(e["kind"] == "stale" and e["decision"] == "pending" for e in remediation)
    assert all(e["requires_remediation"] is True for e in remediation)


def test_merge_idempotent_no_duplicates():
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    counts = merge_stale_entries(remediation, [_stale(1)])
    assert len(remediation) == 1
    assert counts["added"] == 0


def test_merge_refreshes_reasons_and_preserves_decision():
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1, reasons=["规则已停用：旧"])])
    remediation[0]["decision"] = "remediate"
    counts = merge_stale_entries(remediation, [_stale(1, reasons=["法规已废止：新"])])
    assert counts["refreshed"] == 1
    assert remediation[0]["reasons"] == ["法规已废止：新"]
    assert remediation[0]["decision"] == "remediate"  # 人工决策保留


def test_merge_same_reasons_not_counted_as_refreshed():
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    counts = merge_stale_entries(remediation, [_stale(1)])
    assert counts["refreshed"] == 0


def test_merge_resolves_recovered_pending():
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    counts = merge_stale_entries(remediation, [])
    assert counts["resolved"] == 1
    assert remediation[0]["decision"] == "done"
    assert "依据已恢复" in remediation[0]["resolved"]


def test_merge_resolves_recovered_in_progress():
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    remediation[0]["decision"] = "remediate"
    counts = merge_stale_entries(remediation, [])
    assert counts["resolved"] == 1
    assert remediation[0]["decision"] == "done"


def test_merge_keeps_rejected_after_recovery():
    """人工驳回的条目：依据恢复时不动（决策是人的，不自动改写）。"""
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    remediation[0]["decision"] = "reject"
    counts = merge_stale_entries(remediation, [])
    assert counts["resolved"] == 0
    assert remediation[0]["decision"] == "reject"


def test_merge_reopens_system_closed_entry():
    """系统因依据恢复关闭的条目再次失效 → 自愈重开为 pending。"""
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    merge_stale_entries(remediation, [])  # 恢复 → 系统关闭
    assert remediation[0]["resolved"]
    counts = merge_stale_entries(remediation, [_stale(1)])  # 再次失效
    assert counts["reopened"] == 1
    assert remediation[0]["decision"] == "pending"
    assert "resolved" not in remediation[0]


def test_merge_does_not_reopen_retest_closed_entry():
    """复测通过关闭（无 resolved 标记）的条目再次失效 → 不自愈重开。"""
    remediation: list[dict] = []
    merge_stale_entries(remediation, [_stale(1)])
    remediation[0]["decision"] = "done"  # 人工/复测关闭
    counts = merge_stale_entries(remediation, [_stale(1)])
    assert counts["reopened"] == 0
    assert remediation[0]["decision"] == "done"


def test_merge_ignores_review_entries():
    """审查整改项（kind 缺失，task 命名空间）不受 stale 合并影响。"""
    review_entry = {"task_id": 5, "material_id": 1, "decision": "pending"}
    remediation = [review_entry]
    merge_stale_entries(remediation, [_stale(1)])
    assert review_entry["decision"] == "pending"
    assert len(remediation) == 2  # stale 条目独立追加，靠 kind 区分


# ---------- DB 用例：容器幂等 / 键兼容回归 ----------


@_db_required
def test_container_lazy_create_idempotent():
    db = SessionLocal()
    created = False
    try:
        existing = (
            db.query(ImpactAssessment)
            .filter(ImpactAssessment.title == STALE_CONTAINER_TITLE)
            .first()
        )
        created = existing is None
        c1 = get_or_create_stale_container(db)
        c2 = get_or_create_stale_container(db)
        assert c1.id == c2.id
    finally:
        if created:
            db.query(ImpactAssessment).filter(
                ImpactAssessment.title == STALE_CONTAINER_TITLE
            ).delete(synchronize_session=False)
            db.commit()
        db.close()


@_db_required
def test_sync_batch_no_crash_with_stale_entries():
    """键兼容回归：容器含 stale 条目时，复测批次回写不再 KeyError（旧实现必崩）。"""
    db = SessionLocal()
    created_container = False
    batch_id = None
    snapshot = None
    try:
        existing = (
            db.query(ImpactAssessment)
            .filter(ImpactAssessment.title == STALE_CONTAINER_TITLE)
            .first()
        )
        created_container = existing is None
        container = get_or_create_stale_container(db)
        snapshot = list((container.items or {}).get("remediation") or [])

        # 手工注入一条 stale 待更新项（无 task_id）
        items = container.items or {}
        remediation = list(items.get("remediation") or [])
        remediation.append(
            {
                "kind": "stale",
                "material_id": 999999,
                "material_name": "键兼容回归-材料",
                "reasons": ["规则已停用：回归"],
                "requires_remediation": True,
                "decision": "pending",
            }
        )
        items["remediation"] = remediation
        container.items = items
        flag_modified(container, "items")
        db.commit()

        batch = ReviewBatch(
            batch_name="键兼容回归批次",
            total_count=0,
            status="completed",
            source_type="impact_assessment",
            source_id=container.id,
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

        sync_batch_to_assessment(db, batch_id)  # 旧实现此处 KeyError

        db.expire_all()
        refreshed = db.get(ImpactAssessment, container.id)
        entries = (refreshed.items or {}).get("remediation") or []
        assert any(
            e.get("kind") == "stale" and e.get("material_id") == 999999 for e in entries
        )
    finally:
        if snapshot is not None and not created_container:
            container = get_or_create_stale_container(db)
            items = container.items or {}
            items["remediation"] = snapshot
            container.items = items
            flag_modified(container, "items")
        if batch_id is not None:
            db.query(ReviewBatch).filter(ReviewBatch.id == batch_id).delete(
                synchronize_session=False
            )
        if created_container:
            db.query(ImpactAssessment).filter(
                ImpactAssessment.title == STALE_CONTAINER_TITLE
            ).delete(synchronize_session=False)
        db.commit()
        db.close()


@_db_required
def test_decide_remediation_by_material_id():
    """stale 条目无 task_id：按 material_id 定位决策（API 层同此路径）。"""
    db = SessionLocal()
    created_container = False
    snapshot = None
    try:
        existing = (
            db.query(ImpactAssessment)
            .filter(ImpactAssessment.title == STALE_CONTAINER_TITLE)
            .first()
        )
        created_container = existing is None
        container = get_or_create_stale_container(db)
        snapshot = list((container.items or {}).get("remediation") or [])

        items = container.items or {}
        remediation = list(items.get("remediation") or [])
        remediation.append(
            {
                "kind": "stale",
                "material_id": 999998,
                "material_name": "决策回归-材料",
                "reasons": ["规则已停用：回归"],
                "requires_remediation": True,
                "decision": "pending",
            }
        )
        items["remediation"] = remediation
        container.items = items
        flag_modified(container, "items")
        db.commit()

        result = decide_remediation(db, container.id, "remediate", material_id=999998)
        entry = next(e for e in result if e.get("material_id") == 999998)
        assert entry["decision"] == "remediate"
    finally:
        if snapshot is not None and not created_container:
            container = get_or_create_stale_container(db)
            items = container.items or {}
            items["remediation"] = snapshot
            container.items = items
            flag_modified(container, "items")
        if created_container:
            db.query(ImpactAssessment).filter(
                ImpactAssessment.title == STALE_CONTAINER_TITLE
            ).delete(synchronize_session=False)
        db.commit()
        db.close()
