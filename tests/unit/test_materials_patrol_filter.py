"""材料台账 patrol_status 过滤（PR-1 驾驶舱卡片下钻的后端支撑）。

驾驶舱「线上内容已变更 / 线上页面失联」卡片下钻到
`/materials?filter=patrol_changed|patrol_gone`，后端列表端点为此新增
`patrol_status` 可选过滤参数——本文件锁定该参数的语义。

直调路由函数（不经 HTTP 层）：过滤是查询构造逻辑，直调可精准锁定参数语义，
且不依赖认证链路（该端点 body 未使用 current_user）。
"""

import pytest
from sqlalchemy import text
from src.api.routers.impact import list_materials
from src.infrastructure.database.mysql import SessionLocal
from src.models import ProductMaterial

_SAMPLE_NAMES = ("PR1下钻样本-changed", "PR1下钻样本-ok", "PR1下钻样本-gone")


@pytest.fixture()
def patrol_samples():
    """造三条不同 patrol_status 的在用材料（唯一名），结束后删除。"""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("MySQL 不可用，跳过")

    created: list[int] = []
    try:
        for name, status in zip(_SAMPLE_NAMES, ("changed", "ok", "gone"), strict=True):
            material = ProductMaterial(
                name=name,
                product_type="fund",
                material_type="推文",
                version="v1",
                status="active",
                patrol_status=status,
            )
            db.add(material)
            db.flush()
            created.append(material.id)
        db.commit()
    finally:
        db.close()

    yield
    db = SessionLocal()
    try:
        db.query(ProductMaterial).filter(ProductMaterial.id.in_(created)).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def _names_with_filter(patrol_status: str | None) -> list[str]:
    db = SessionLocal()
    try:
        resp = list_materials(
            page=1,
            page_size=200,
            product_type=None,
            status=None,
            last_review_status=None,
            patrol_status=patrol_status,
            db=db,
            current_user=None,  # 该端点 body 未使用 current_user（认证由依赖声明承担）
        )
        return [item["name"] for item in resp["data"]["items"]]
    finally:
        db.close()


def test_patrol_status_changed_filter(patrol_samples):
    """patrol_status=changed：只含 changed 样本（含下钻目标行，不含其它态）。"""
    names = _names_with_filter("changed")
    assert _SAMPLE_NAMES[0] in names
    assert _SAMPLE_NAMES[1] not in names
    assert _SAMPLE_NAMES[2] not in names


def test_patrol_status_gone_filter(patrol_samples):
    """patrol_status=gone：只含 gone 样本。"""
    names = _names_with_filter("gone")
    assert _SAMPLE_NAMES[2] in names
    assert _SAMPLE_NAMES[0] not in names
    assert _SAMPLE_NAMES[1] not in names


def test_no_patrol_filter_returns_all(patrol_samples):
    """不传 patrol_status：不过滤，三条样本都在。"""
    names = _names_with_filter(None)
    assert all(name in names for name in _SAMPLE_NAMES)


def test_patrol_filter_returns_only_matching_status(patrol_samples):
    """结果集内所有行的 patrol_status 均等于过滤值（防止残留行混入）。"""
    db = SessionLocal()
    try:
        resp = list_materials(
            page=1,
            page_size=200,
            product_type=None,
            status=None,
            last_review_status=None,
            patrol_status="ok",
            db=db,
            current_user=None,
        )
        items = resp["data"]["items"]
        assert all(item["patrol_status"] == "ok" for item in items)
    finally:
        db.close()
