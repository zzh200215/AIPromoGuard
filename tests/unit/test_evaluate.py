"""准确率评估管线测试（PRD §14）。

覆盖匹配逻辑与召回/误报口径；不依赖 DB（monkeypatch 掉规则扫描）。
"""

import importlib.util
import json
from pathlib import Path

import pytest

# scripts 非包结构，按文件路径加载 evaluate 模块（脚本本身会把仓库根加入 sys.path）
_EVAL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evaluate" / "evaluate.py"
_spec = importlib.util.spec_from_file_location("evaluate", _EVAL_PATH)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_overlaps_direction_insensitive():
    assert ev._overlaps("保本保收益", "保本保收益")
    assert ev._overlaps("预期年化收益率可达5.8%", "预期年化收益率")  # 标注片段在检出窗口内
    assert ev._overlaps("零风险", "本产品零风险")  # 检出片段在标注文本内
    assert not ev._overlaps("保本保收益", "稳赚不赔")
    assert not ev._overlaps("", "稳赚不赔")


def test_evaluate_case_recall_and_fpr(monkeypatch):
    """标注点全部命中 → 召回 100%；多余检出 → 计入误报。"""
    case = {
        "id": "t1",
        "domain": "banking",
        "ground_truth": [
            {"text": "保本保收益", "risk_level": "high"},
            {"text": "零风险", "risk_level": "medium"},
        ],
    }
    monkeypatch.setattr(
        ev,
        "_scan_rule_engine",
        lambda c: [
            {
                "source": "rule",
                "rule_name": "禁止承诺保本保收益",
                "original_text": "保本保收益",
                "confidence": 0.95,
            },
            {
                "source": "rule",
                "rule_name": "禁止零风险无风险表述",
                "original_text": "零风险",
                "confidence": 0.85,
            },
            {  # 未标注 → 误报
                "source": "rule",
                "rule_name": "禁止限量抢购饥饿营销",
                "original_text": "限时抢购",
                "confidence": 0.85,
            },
        ],
    )
    r = ev._evaluate_case(case, "rule")
    assert r["recall"] == 1.0
    assert r["tp_gt"] == 2
    assert r["fp"] == 1
    assert r["fpr"] == pytest.approx(1 / 3)
    assert r["precision"] == pytest.approx(2 / 3)


def test_evaluate_case_missed_annotation(monkeypatch):
    """标注点未被检出 → 召回下降；无多余检出 → 无误报。"""
    case = {
        "id": "t2",
        "domain": "fund",
        "ground_truth": [
            {"text": "定投稳赚", "risk_level": "high"},
            {"text": "业绩冠军", "risk_level": "medium"},  # 系统漏检
        ],
    }
    monkeypatch.setattr(
        ev,
        "_scan_rule_engine",
        lambda c: [
            {
                "source": "rule",
                "rule_name": "定投稳赚误导",
                "original_text": "定投稳赚",
                "confidence": 0.85,
            },
        ],
    )
    r = ev._evaluate_case(case, "rule")
    assert r["recall"] == 0.5
    assert r["fpr"] == 0.0
    assert r["precision"] == 1.0


def test_evaluate_case_clean_doc_no_gt(monkeypatch):
    """无标注样本：检出为空 → 召回 1.0 / 误报 0；有检出 → 全为误报。"""
    case = {"id": "t3", "domain": "insurance", "ground_truth": []}
    monkeypatch.setattr(ev, "_scan_rule_engine", lambda c: [])
    r = ev._evaluate_case(case, "rule")
    assert r["recall"] == 1.0 and r["fpr"] == 0.0

    monkeypatch.setattr(ev, "_scan_rule_engine", lambda c: [
        {"source": "rule", "rule_name": "x", "original_text": "返还本金", "confidence": 0.85},
    ])
    r = ev._evaluate_case(case, "rule")
    assert r["fpr"] == 1.0 and r["precision"] == 0.0


def test_seed_set_structure():
    """种子基准集结构合法：每条样本有 id/domain/text/ground_truth，标注文本非空。"""
    path = Path(ev.__file__).resolve().parent / "eval_cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["cases"]) >= 10
    for c in data["cases"]:
        assert c["id"] and c["domain"] and c["text"]
        assert isinstance(c["ground_truth"], list)
        for gt in c["ground_truth"]:
            assert gt.get("text"), f"{c['id']} 存在空标注"
            assert gt.get("risk_level") in ("high", "medium", "low")
