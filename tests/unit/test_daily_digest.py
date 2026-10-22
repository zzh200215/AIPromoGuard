"""运转摘要的备份完整性判定（2026-10-19 事故回归）。

背景：10-17/18/19 三次备份只成功拷贝了 chroma（12:30 时 Docker 未启动，
mysqldump 失败），脚本却返回成功——摘要必须能一眼看出"缺件"。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ops.daily_digest import _latest_backup  # noqa: E402


def _mk(base: Path, name: str, files: list[str], manifest: dict | None = None) -> None:
    d = base / name
    d.mkdir(parents=True)
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_complete_manifest_reports_complete(tmp_path):
    _mk(
        tmp_path, "20261019_203049",
        ["mysql.sql", "neo4j.json", "uploads/a.txt", "chroma/chroma.sqlite3"],
        {"components": {"mysql": {"ok": True}, "chroma": {"ok": True},
                        "neo4j": {"ok": True}, "uploads": {"ok": True}}},
    )
    info = _latest_backup(tmp_path)
    assert info["complete"] is True
    assert info["missing"] == []


def test_partial_manifest_reports_missing(tmp_path):
    _mk(
        tmp_path, "20261019_120000", ["chroma/chroma.sqlite3"],
        {"components": {"mysql": {"ok": False, "error": "docker down"},
                        "chroma": {"ok": True}}},
    )
    info = _latest_backup(tmp_path)
    assert info["complete"] is False
    assert info["missing"] == ["mysql"]


def test_legacy_backup_without_manifest_inferred_by_files(tmp_path):
    _mk(tmp_path, "20261017_210229", ["chroma/chroma.sqlite3"])  # 只有 chroma
    info = _latest_backup(tmp_path)
    assert info["complete"] is False
    assert set(info["missing"]) == {"mysql", "neo4j", "uploads"}


def test_no_backup_dir_returns_none(tmp_path):
    assert _latest_backup(tmp_path / "missing") is None
