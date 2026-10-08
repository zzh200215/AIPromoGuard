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
    build_patrol_diff,
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


# ---------- 巡检差异详情（build_patrol_diff：批准版 vs 线上存档快照） ----------

_PD_BASE = "年化收益率 3.85%，最低认购 50,000 元，持有期限 366 天。"
_PD_ONLINE = "年化收益率 9.85%，最低认购 50,000 元，持有期限 366 天。"


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
class TestPatrolDiffDB:
    """材料台账「差异详情」抽屉的数据构建：available 判定 / 数字缺失 / 片段 / 复审任务回指。"""

    @pytest.fixture
    def db(self):
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def ctx(self, db, tmp_path, monkeypatch):
        """独立 upload_dir + 材料 + 批准版文档；返回 (material, upload_root, doc_id)。"""
        import uuid
        from types import SimpleNamespace

        import src.services.content_patrol as cp_mod

        upload_root = tmp_path / "uploads"
        doc_id = f"doc_pd{uuid.uuid4().hex[:8]}"
        doc_dir = upload_root / "1"
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / f"{doc_id}.txt").write_text(_PD_BASE, encoding="utf-8")

        monkeypatch.setattr(
            cp_mod, "settings", SimpleNamespace(upload_dir=str(upload_root))
        )

        m = ProductMaterial(
            name="差异详情测试材料",
            product_type="fund",
            material_type="单页",
            status="active",
            document_id=doc_id,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        yield m, upload_root, doc_id
        db.query(ReviewTask).filter(
            ReviewTask.document_path.like(f"%doc_patrol_{m.id}_%")
        ).delete(synchronize_session=False)
        db.query(ProductMaterial).filter(ProductMaterial.id == m.id).delete(
            synchronize_session=False
        )
        db.expire_all()
        db.commit()

    def test_available_diff_with_missing_number_and_fragments(self, db, ctx):
        material, upload_root, _ = ctx
        patrol_dir = upload_root / "patrol"
        patrol_dir.mkdir(parents=True, exist_ok=True)
        (patrol_dir / f"doc_patrol_{material.id}_20261008120000.txt").write_text(
            _PD_ONLINE, encoding="utf-8"
        )
        material.patrol_status = "changed"
        db.commit()

        diff = build_patrol_diff(db, material)
        assert diff["available"] is True
        assert diff["similarity"] is not None and diff["similarity"] < 1.0
        assert "3.85" in diff["missing_numbers"]  # 批准版收益率在线上消失
        assert diff["change_count"] >= 1
        assert any("9.85" in c["new_text"] for c in diff["changes"])
        assert diff["online_archived_at"] == "2026-10-08 12:00:00"
        assert diff["review_task_id"] is None  # 未创建复审任务时回指为空

    def test_review_task_backlink(self, db, ctx):
        """changed 触发复审任务后，抽屉可回指任务（「查看复审任务」按钮数据源）。"""
        material, upload_root, _ = ctx
        patrol_dir = upload_root / "patrol"
        patrol_dir.mkdir(parents=True, exist_ok=True)
        (patrol_dir / f"doc_patrol_{material.id}_20261008120000.txt").write_text(
            _PD_ONLINE, encoding="utf-8"
        )
        task = ReviewTask(
            task_name=f"[巡检] {material.name} 线上内容变更复审",
            document_name=f"doc_patrol_{material.id}_20261008120000.txt",
            document_path=str(patrol_dir / f"doc_patrol_{material.id}_20261008120000.txt"),
            document_type="txt",
            status="pending",
            created_by=None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        diff = build_patrol_diff(db, material)
        assert diff["review_task_id"] == task.id

    def test_no_snapshot_reason_by_status(self, db, ctx):
        """无快照时按巡检状态给出可读原因（gone 讲清"页面下线，无内容可比"）。"""
        material, _, _ = ctx
        material.patrol_status = "gone"
        db.commit()
        diff = build_patrol_diff(db, material)
        assert diff["available"] is False
        assert "已下线" in (diff["reason"] or "")

        material.patrol_status = "drift"
        db.commit()
        diff = build_patrol_diff(db, material)
        assert diff["available"] is False
        assert "漂移" in (diff["reason"] or "")

    def test_archive_without_approved_doc(self, db, tmp_path, monkeypatch):
        """有线上快照但材料未关联批准版文档 → 明确报因，不假装可比。"""
        from types import SimpleNamespace

        import src.services.content_patrol as cp_mod

        upload_root = tmp_path / "uploads2"
        patrol_dir = upload_root / "patrol"
        patrol_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            cp_mod, "settings", SimpleNamespace(upload_dir=str(upload_root))
        )
        m = ProductMaterial(
            name="无批准版差异测试", product_type="fund", material_type="推文",
            status="active", document_id=None,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        try:
            (patrol_dir / f"doc_patrol_{m.id}_20261008120000.txt").write_text(
                _PD_ONLINE, encoding="utf-8"
            )
            diff = build_patrol_diff(db, m)
            assert diff["available"] is False
            assert "批准版" in (diff["reason"] or "")
        finally:
            db.delete(m)
            db.commit()
