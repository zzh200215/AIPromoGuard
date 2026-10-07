"""发布后内容巡检单测（R3-1）：mock fetcher 零网络.

覆盖：相似度三档判定 / gone-error 分类 / 基线建立与回写 / changed 触发
复审任务（created_by=None + 对比基线挂批准版）/ 批量入口与计数。
DB 用例遵循项目约定：真实 SessionLocal + 数据库不可用自动 skip +
isolated_materials 隔离（防演示种子污染批量巡检）。
"""


import pytest
from src.infrastructure.database.mysql import SessionLocal
from src.models import ProductMaterial, ReviewTask
from src.services.content_patrol import (
    PatrolError,
    containment,
    normalize_for_compare,
    patrol_materials,
    similarity,
)


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        return True
    except Exception:  # noqa: BLE001
        return False


_db_required = pytest.mark.skipif(not _db_ready(), reason="数据库不可用")

# ---------- 归一化与相似度（纯函数，无 DB，不 skip） ----------

def test_normalize_strips_whitespace_and_punct():
    a = "年化收益率 3.85%，最低认购 50,000 元"
    b = "年化收益率3.85%最低认购50000元"
    assert normalize_for_compare(a) == normalize_for_compare(b)


def test_similarity_thresholds():
    base = "年化收益率 3.85%，最低认购 50,000 元，持有期限 366 天，风险提示：过往业绩不代表未来表现"
    assert similarity(base, base) >= 0.98  # 未变更
    changed = base.replace("3.85%", "9.85%").replace("366", "36") + "限时抢购立即扫码"
    assert similarity(base, changed) < 0.90  # 实质变更


def test_containment_is_noise_immune():
    """containment 对网页噪声免疫：基线内容全保留 + 大量无关噪声 = 未变更。"""
    base = "年化收益率 3.85%，最低认购 50,000 元，持有期限 366 天，风险提示：过往业绩不代表未来表现"
    noisy = base + "\n首页 | 产品 | 关于我们 | 联系客服 | 沪ICP备12345678号 | 2026-10-05 12:00:00"
    assert containment(base, base) >= 0.98
    assert containment(base, noisy) >= 0.98  # 双向 ratio 0.77 会误报，containment 正确判 ok


# ---------- DB 用例（数据库不可用整体 skip） ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
class TestPatrolDB:
    @pytest.fixture
    def db(self):
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def material(self, db):
        m = ProductMaterial(
            name="巡检测试海报",
            product_type="wealth",
            material_type="海报",
            status="active",
            document_id="doc_abcd1234",
            publish_url="https://example.com/poster",
            channel="web",
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        yield m
        # 清理：巡检可能创建复审任务与存档文件（clean_review_data 会清任务行）
        db.query(ReviewTask).filter(
            ReviewTask.task_name.like(f"[巡检] {m.name}%")
        ).delete(synchronize_session=False)
        db.query(ProductMaterial).filter(ProductMaterial.id == m.id).delete(
            synchronize_session=False
        )
        # synchronize_session=False 的 bulk delete 不会同步 identity map——
        # 已删对象仍是 persistent 态，teardown 的 close/后续 flush 会对其发
        # UPDATE（0 rows matched）→ StaleDataError。expire_all 丢弃这些对象。
        db.expire_all()
        db.commit()

    @pytest.fixture
    def baseline_doc(self, db, tmp_path, monkeypatch, material):
        """批准版文档（巡检基线来源）+ upload_dir 指向 tmp + start_review 静默.

        项目惯例：pydantic v2 settings 不能 setattr 未声明方法，统一替换
        使用方模块的 settings 引用（SimpleNamespace）。
        """
        from types import SimpleNamespace

        import src.services.content_patrol as cp_mod
        import src.services.review_service as rs_mod

        upload_root = tmp_path / "uploads"
        doc_dir = upload_root / "1"
        doc_dir.mkdir(parents=True, exist_ok=True)
        doc = doc_dir / f"{material.document_id}.txt"
        doc.write_text(
            "年化收益率 3.85%，最低认购 50,000 元，持有期限 366 天。"
            "风险提示：过往业绩不代表未来表现，市场有风险投资须谨慎。",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            cp_mod, "settings", SimpleNamespace(upload_dir=str(upload_root))
        )
        # 巡检复审任务会经函数内 import 调 start_review（起线程池跑真审查），
        # 单测里静默化——复审任务本身的执行是 review_service 测试的职责
        monkeypatch.setattr(rs_mod, "start_review", lambda task_id: None)
        return doc

    def test_patrol_ok_when_unchanged(self, db, material, baseline_doc):
        base_text = baseline_doc.read_text(encoding="utf-8")
        outcome = patrol_materials(db, [material.id], fetcher=lambda url: base_text)
        assert outcome["counts"]["ok"] == 1
        assert material.patrol_status == "ok"
        assert material.content_fingerprint  # 基线已回写

    def test_patrol_drift_observed(self, db, material, baseline_doc):
        base_text = baseline_doc.read_text(encoding="utf-8")
        drift_text = base_text + "\n版权所有 © XX基金 2026"
        outcome = patrol_materials(db, [material.id], fetcher=lambda url: drift_text)
        assert outcome["counts"]["drift"] == 1
        assert material.patrol_status == "drift"
        assert db.query(ReviewTask).filter(
            ReviewTask.task_name.like("[巡检]%")
        ).count() == 0  # 漂移不触发复审

    def test_patrol_changed_creates_review_task(self, db, material, baseline_doc):
        base_text = baseline_doc.read_text(encoding="utf-8")
        changed = base_text.replace("3.85%", "9.85%").replace("366", "36") + "限时抢购立即扫码"
        outcome = patrol_materials(db, [material.id], fetcher=lambda url: changed)
        assert outcome["counts"]["changed"] == 1
        assert material.patrol_status == "changed"
        task = db.query(ReviewTask).filter(
            ReviewTask.task_name.like("[巡检]%")
        ).one()
        assert task.created_by is None  # 系统发起
        assert task.base_document_path == str(baseline_doc)  # 对比基线=批准版
        assert outcome["outcomes"][0]["review_task_id"] == task.id

    def test_patrol_gone_marks_material(self, db, material, baseline_doc):
        def _gone(url):
            raise PatrolError("gone", "页面已下线（HTTP 404）")

        outcome = patrol_materials(db, [material.id], fetcher=_gone)
        assert outcome["counts"]["gone"] == 1
        assert material.patrol_status == "gone"

    def test_patrol_error_keeps_material(self, db, material, baseline_doc):
        def _error(url):
            raise PatrolError("error", "超时")

        outcome = patrol_materials(db, [material.id], fetcher=_error)
        assert outcome["counts"]["error"] == 1
        assert material.patrol_status == "error"

    def test_patrol_skips_materials_without_url(self, db):
        m = ProductMaterial(
            name="无渠道材料-巡检测试", product_type="fund", material_type="推文",
            status="active",
        )
        db.add(m)
        db.commit()
        try:
            outcome = patrol_materials(db, None, fetcher=lambda url: "x")
            assert outcome["checked"] == 0  # 未登记 publish_url 的不巡检
            assert m.patrol_status is None
        finally:
            db.delete(m)
            db.commit()

    def test_patrol_baseline_unresolvable_marks_error(self, db, material, monkeypatch):
        """批准版文档缺失 → 无法建基线 → error（诚实报错而非假装 ok）。"""
        from types import SimpleNamespace

        import src.services.content_patrol as cp_mod

        monkeypatch.setattr(
            cp_mod, "settings", SimpleNamespace(upload_dir="Z:/nonexistent-uploads")
        )
        outcome = patrol_materials(db, [material.id], fetcher=lambda url: "任意内容")
        assert outcome["counts"]["error"] == 1
        assert material.patrol_status == "error"

    def test_patrol_two_layer_verdict(self, db, material, baseline_doc):
        """双层判定端到端：数字被改（containment ≈0.95 不达 changed 线）必须判 changed。"""
        base_text = baseline_doc.read_text(encoding="utf-8")
        # 只改一个数字字符（3.85→9.85），字符级 containment ≈0.95 高于 drift 阈值，
        # 但关键数字缺失 → 双层判定升级 changed
        tampered = base_text.replace("3.85%", "9.85%")
        outcome = patrol_materials(db, [material.id], fetcher=lambda url: tampered)
        assert outcome["counts"]["changed"] == 1
        assert material.patrol_status == "changed"

        # 非数字文字漂移（数字全保留）→ drift
        drifted = base_text.replace("过往业绩", "历史业绩")
        outcome2 = patrol_materials(db, [material.id], fetcher=lambda url: drifted)
        assert outcome2["counts"]["drift"] == 1
        assert material.patrol_status == "drift"
