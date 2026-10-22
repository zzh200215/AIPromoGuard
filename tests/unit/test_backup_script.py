"""backup.py 的参数解析与保留策略单元测试（脚本经 importlib 加载，不执行 main）。"""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup" / "backup.py"
_spec = importlib.util.spec_from_file_location("backup_script", _SCRIPT)
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


def test_parse_args_defaults():
    out, keep = backup._parse_args([])
    assert out == Path("data/backups")
    assert keep == 0


def test_parse_args_out_and_keep():
    out, keep = backup._parse_args(["--out", "D:/tmp/bk", "--keep", "14"])
    assert out == Path("D:/tmp/bk")
    assert keep == 14


def test_parse_args_ignores_unknown():
    out, keep = backup._parse_args(["--wat"])
    assert out == Path("data/backups")
    assert keep == 0


def test_prune_keeps_newest_n_and_skips_foreign_entries(tmp_path):
    for name in ("20260101_000000", "20260202_000000", "20260303_000000", "20260404_000000"):
        (tmp_path / name).mkdir()
    (tmp_path / "not-a-backup").mkdir()  # 非时间戳目录不应被清理
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    removed = backup._prune_old(tmp_path, 2)
    assert removed == ["20260101_000000", "20260202_000000"]
    assert (tmp_path / "20260303_000000").exists()
    assert (tmp_path / "20260404_000000").exists()
    assert (tmp_path / "not-a-backup").exists()
    assert (tmp_path / "notes.txt").exists()


def test_prune_noop_when_under_limit(tmp_path):
    (tmp_path / "20260101_000000").mkdir()
    assert backup._prune_old(tmp_path, 5) == []


def test_prune_zero_keep_or_missing_base(tmp_path):
    (tmp_path / "20260101_000000").mkdir()
    assert backup._prune_old(tmp_path, 0) == []
    assert backup._prune_old(tmp_path / "nope", 3) == []
