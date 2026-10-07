"""证据包导出单测（R1-2）：纯函数零 DB，重点验证"包内内容与留痕一致".

验收口径（产品升级方案.md R1-2）：zip 内容与数据库留痕逐条对得上——
以 manifest 的 SHA256 与实际文件字节比对作为完整性自检。
"""

import csv
import hashlib
import io
import json
import zipfile

from src.services.evidence_pack import build_evidence_zip

_REPORT = {
    "task_id": 7,
    "file_name": "理财产品海报.png",
    "summary": {"total_violations": 3, "high_risk": 2, "medium_risk": 1, "low_risk": 0},
    "sign_off": {
        "decision": "released",
        "username": "合规张三",
        "note": "已整改复核",
        "created_at": "2026-10-04T10:00:00",
    },
    "violations": [
        {
            "violation_type": "rule",
            "risk_level": "high",
            "original_text": "保本保收益",
            "location_page": 1,
            "location_paragraph": 3,
            "status": "confirmed",
            "confidence_score": 1.0,
            "evidence_supported": None,
            "rule_name": "禁止刚性兑付",
            "description": "命中禁止性表述",
        },
        {
            "violation_type": "llm",
            "risk_level": "medium",
            "original_text": "预期收益率高达 99%",
            "location_page": 1,
            "location_paragraph": 5,
            "status": "pending_confirm",
            "confidence_score": 0.72,
            "evidence_supported": False,
            "rule_name": "夸大收益",
            "description": "疑似夸大表述",
        },
        {
            "violation_type": "hybrid",
            "risk_level": "high",
            "original_text": "稳赚不赔",
            "location_page": 2,
            "location_paragraph": 1,
            "status": "false_positive",
            "confidence_score": 0.95,
            "evidence_supported": True,
            "rule_name": "保本表述",
            "description": "交叉命中后人工翻案",
        },
    ],
}

_META = {
    "task_id": 7,
    "file_name": "理财产品海报.png",
    "status": "completed",
    "created_at": "2026-10-04T09:00:00",
    "completed_at": "2026-10-04T09:05:00",
    "sign_off_count": 1,
}


def _build():
    return build_evidence_zip(
        report=_REPORT,
        report_md="# 审查报告\n正文",
        report_json=json.dumps(_REPORT, ensure_ascii=False, indent=2),
        operations=[
            {
                "created_at": "2026-10-04T09:06:00",
                "username": "合规张三",
                "action": "result.confirm",
                "resource_type": "review_result",
                "resource_id": "101",
                "detail": '{"verdict": "confirmed"}',
            },
            {
                "created_at": "2026-10-04T09:10:00",
                "username": "合规李四",
                "action": "task.sign_off",
                "resource_type": "task",
                "resource_id": "7",
                "detail": None,
            },
        ],
        meta=_META,
    )


_EXPECTED_FILES = {
    "审查报告.md", "审查报告.json", "结论生命周期.csv", "操作留痕.csv", "manifest.json",
}


def test_zip_contains_expected_files():
    zf = zipfile.ZipFile(io.BytesIO(_build()))
    assert set(zf.namelist()) == _EXPECTED_FILES


def test_manifest_sha256_matches_actual_files():
    """验收核心：manifest 记录的 SHA256 与包内实际文件逐字节一致。"""
    data = _build()
    zf = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    for name, info in manifest["files"].items():
        actual = hashlib.sha256(zf.read(name)).hexdigest()
        assert actual == info["sha256"], f"{name} 内容与 manifest 不一致"
        assert len(zf.read(name)) == info["bytes"]
    assert manifest["task"]["task_id"] == 7
    assert manifest["task"]["file_name"] == "理财产品海报.png"


def test_report_md_and_json_preserved():
    zf = zipfile.ZipFile(io.BytesIO(_build()))
    assert zf.read("审查报告.md").decode("utf-8") == "# 审查报告\n正文"
    report = json.loads(zf.read("审查报告.json").decode("utf-8"))
    assert len(report["violations"]) == 3
    assert report["sign_off"]["username"] == "合规张三"


def test_lifecycle_csv_rows_match_violations():
    """CSV 行数与结论条数一致、状态映射与留痕一致。"""
    zf = zipfile.ZipFile(io.BytesIO(_build()))
    rows = list(csv.reader(io.StringIO(zf.read("结论生命周期.csv").decode("utf-8-sig"))))
    assert len(rows) == 1 + 3  # 表头 + 3 条结论
    header, r1, r2, r3 = rows
    assert header[5] == "最终状态" and header[7] == "证据核验"
    assert r1[2] == "high" and r1[5] == "已确认" and r1[7] == "不适用"
    assert r2[5] == "待复核" and r2[7] == "不可支撑"
    assert r3[5] == "已剔除误报" and r3[7] == "可支撑"


def test_operations_csv_rows_match_audit():
    zf = zipfile.ZipFile(io.BytesIO(_build()))
    rows = list(csv.reader(io.StringIO(zf.read("操作留痕.csv").decode("utf-8-sig"))))
    assert len(rows) == 1 + 2
    assert rows[1][2] == "result.confirm"
    assert rows[2][1] == "合规李四" and rows[2][3] == "task"


def test_empty_report_produces_valid_zip():
    """空结论边界：仍产出合法 zip，CSV 只有表头，manifest 完整。"""
    data = build_evidence_zip(
        report={"violations": [], "sign_off": None},
        report_md="# 空",
        report_json="{}",
        operations=[],
        meta={"task_id": 1, "file_name": "x.png", "status": "completed",
             "created_at": None, "completed_at": None, "sign_off_count": 0},
    )
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert set(zf.namelist()) == _EXPECTED_FILES
    lifecycle = list(csv.reader(io.StringIO(zf.read("结论生命周期.csv").decode("utf-8-sig"))))
    assert len(lifecycle) == 1  # 仅表头
