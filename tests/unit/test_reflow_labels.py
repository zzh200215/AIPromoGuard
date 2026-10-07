"""方向③ 数据闭环·回流任务纯函数测试（不依赖 DB，只测去重/投影/样本构建）。"""

import importlib.util
from pathlib import Path

_REFLOW_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evaluate" / "reflow_labels.py"
_spec = importlib.util.spec_from_file_location("reflow_labels", _REFLOW_PATH)
rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf)


# ---------- 指纹 / 样本构建 ----------

def test_fingerprint_normalizes_whitespace():
    assert rf.fingerprint(" 保本\n保收益 ") == rf.fingerprint("保本保收益")
    assert len(rf.fingerprint("x")) == 64  # sha256 hex


def test_seed_case_marks_rule_source():
    c = rf._seed_case(
        {"id": "banking_001", "domain": "banking", "text": "派文",
         "ground_truth": [{"text": "保本", "risk_level": "high", "rule_name": "R1"}]}
    )
    assert c["origin"] == "synthetic"
    assert c["case_key"] == "syn:banking_001"
    assert c["ground_truth"] == [
        {"text": "保本", "risk_level": "high", "rule_name": "R1", "source": "rule"}
    ]
    assert c["negative_ground_truth"] == []


def _row(result_id, status, text, vtype="rule", rule_name="R", risk="medium", desc=None):
    return {
        "result_id": result_id, "task_id": 5, "original_text": text, "status": status,
        "violation_type": vtype, "risk_level": risk, "confirmed_at": None,
        "description": desc, "rule_name": rule_name, "rule_domain": "banking",
        "document_path": "/f.txt", "task_domain": "banking",
    }


def test_build_task_case_mixed_confirmed_and_fp():
    """混合任务：confirmed 进 ground_truth、FP 进 negative_ground_truth（不再整份跳过）。"""
    case = rf.build_task_case(
        5,
        [
            _row(1, "confirmed", "违规保本", rule_name="R1", risk="high"),
            _row(2, "false_positive", "不承诺保本", rule_name="R2"),
        ],
        "派文全文",
        "banking",
    )
    assert case["id"] == "hr_5"
    assert [g["text"] for g in case["ground_truth"]] == ["违规保本"]
    assert [n["text"] for n in case["negative_ground_truth"]] == ["不承诺保本"]
    assert case["origin"] == "human_review"


# ---------- 只增不减合并 ----------

def test_merge_adds_new_then_replaces_same_task():
    c1 = rf.build_task_case(1, [_row(1, "confirmed", "保本")], "doc", "banking")
    c1b = rf.build_task_case(1, [_row(1, "false_positive", "保本")], "doc", "banking")  # 翻案
    c2 = rf.build_task_case(2, [_row(3, "confirmed", "零风险", rule_name="R2")], "doc2", "fund")

    reg, added, updated = rf.merge_cases([], [c1])
    assert added == ["hr_1"] and updated == []

    reg, added, updated = rf.merge_cases(reg, [c1b, c2])
    assert added == ["hr_2"]  # 只新增 doc2
    assert updated == ["hr_1"]  # 同任务翻案就地替换
    by_id = {c["id"]: c for c in reg}
    assert by_id["hr_1"]["ground_truth"] == []  # 已翻案为误报
    assert len(by_id["hr_1"]["negative_ground_truth"]) == 1
    # 只增不减：案例总数可验证
    assert len(reg) == 2


def test_merge_same_fingerprint_different_task_merges_lineage():
    c1 = rf.build_task_case(1, [_row(1, "confirmed", "保本")], "同一份文档", "banking")
    c2 = rf.build_task_case(2, [_row(3, "confirmed", "保本")], "同一份文档", "banking")
    reg, added, updated = rf.merge_cases([c1], [c2])
    assert added == []  # 同文档不重复加案
    assert updated == ["hr_1"]
    assert reg[0]["lineage"]["task_ids"] == [1, 2]
    assert reg[0]["lineage"]["result_ids"] == [1, 3]


def test_merge_seed_idempotent():
    seed = [rf._seed_case({"id": "a", "domain": "banking", "text": "x",
                           "ground_truth": [{"text": "保本"}]})]
    reg, added1, _ = rf.merge_cases([], seed)
    reg, added2, _ = rf.merge_cases(reg, seed)
    assert len(reg) == 1 and added1 == ["a"] and added2 == []


# ---------- 门禁投影 / 全量集 ----------

def test_project_gate_cases_filters_llm_only():
    cases = [
        # 规则确认 → 进门禁
        rf.build_task_case(1, [_row(1, "confirmed", "保本", vtype="rule")], "d1", "banking"),
        # 仅 LLM 确认（无规则标注、无负面）→ 不进规则门禁
        rf.build_task_case(2, [_row(3, "confirmed", "换个说法", vtype="llm")], "d2", "banking"),
        # 纯误报 → 作负面案例进规则门禁（找系统误触发）
        rf.build_task_case(3, [_row(5, "false_positive", "不保本")], "d3", "banking"),
        # 合成干净文档（gt 为空）→ 本就是守误报的负面样本，必须保留
        rf._seed_case({"id": "syn_clean", "domain": "banking", "text": "合规文档",
                       "ground_truth": []}),
    ]
    gate = rf.project_gate_cases(cases)
    ids = {c["id"] for c in gate}
    assert ids == {"hr_1", "hr_3", "syn_clean"}
    g_neg = next(c for c in gate if c["id"] == "hr_3")
    assert g_neg["ground_truth"] == [] and len(g_neg["negative_ground_truth"]) == 1
    g_clean = next(c for c in gate if c["id"] == "syn_clean")
    assert g_clean["ground_truth"] == [] and g_clean["negative_ground_truth"] == []


def test_to_full_case_shape():
    c = rf.build_task_case(1, [_row(1, "confirmed", "保本", rule_name="R1", risk="high"),
                               _row(2, "false_positive", "不保本")], "doc", "banking")
    full = rf.to_full_case(c)
    assert full["id"] == "hr_1"
    assert full["ground_truth"][0]["text"] == "保本"
    assert "source" not in full["ground_truth"][0]  # 对外评估格式不带内部来源字段
    assert len(full["negative_ground_truth"]) == 1
