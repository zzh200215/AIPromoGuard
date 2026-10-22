"""罚单-法规关联回填脚本的纯函数测试（merge_reg_ids）。"""

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "maintenance"
    / "backfill_case_reg_links.py"
)
_spec = importlib.util.spec_from_file_location("backfill_case_reg_links", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_merge_keeps_existing_and_adds_new():
    assert mod.merge_reg_ids([22, 5], [22, 31]) == [5, 22, 31]


def test_merge_handles_none_and_str_ids():
    # 旧数据可能是字符串数字（JSON 迁移痕迹）——统一归一为 int
    assert mod.merge_reg_ids(None, [3, 1]) == [1, 3]
    assert mod.merge_reg_ids(["22", 7], [22]) == [7, 22]


def test_merge_is_idempotent():
    once = mod.merge_reg_ids([2, 9], [4])
    twice = mod.merge_reg_ids(once, [4])
    assert once == twice == [2, 4, 9]


def test_merge_handles_double_encoded_json():
    # 实测库里的脏形态：JSON 列里存了字符串
    assert mod.merge_reg_ids('[22, "30"]', [22, 31]) == [22, 30, 31]


def test_merge_skips_garbage():
    assert mod.merge_reg_ids("not-json", [5]) == [5]
    assert mod.merge_reg_ids("", [5]) == [5]
    assert mod.merge_reg_ids(["x", 3], []) == [3]
