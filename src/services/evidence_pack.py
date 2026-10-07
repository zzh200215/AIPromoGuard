"""监管取证证据包导出（R1-2，对标 Greenboard books-and-records）.

监管现场检查问"当时凭什么放行"时的一键举证包：报告 + 结论生命周期 +
双引擎命中详情 + 操作留痕，zip 内 manifest 记录每个文件的 SHA256，
包自身可验证完整性（文件被事后篡改即可发现）。

设计约束：
- build_evidence_zip 为纯函数（输入 dict/list，输出 bytes），单测零 DB；
  collect_evidence 只做 DB 查询组装，路由层薄调用；
- 报告文件直接取 task.report_path 落盘的 .md/.json（refresh_report 已按
  最新人工结论回写），保证"包内内容 == 数据库留痕"的一致性承诺；
- CSV 用 utf-8-sig（Excel 打开中文不乱码）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import AuditLog, ReviewResult, TaskSignOff

_STATUS_LABEL = {
    "pending_confirm": "待复核",
    "confirmed": "已确认",
    "false_positive": "已剔除误报",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lifecycle_csv(report: dict) -> bytes:
    """每条结论的生命周期：检出 → 复核/自动确认 → 最终状态。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "序号", "结论来源", "风险等级", "原文片段", "位置(页/段)",
            "最终状态", "置信度", "证据核验", "规则/问题", "说明",
        ]
    )
    for i, v in enumerate(report.get("violations", []), start=1):
        evidence = v.get("evidence_supported")
        w.writerow(
            [
                i,
                v.get("violation_type", ""),
                v.get("risk_level", ""),
                (v.get("original_text") or "")[:120],
                f"{v.get('location_page') or '-'}/{v.get('location_paragraph') or '-'}",
                _STATUS_LABEL.get(v.get("status"), v.get("status", "")),
                v.get("confidence_score", ""),
                "可支撑" if evidence is True else "不可支撑" if evidence is False else "不适用",
                v.get("rule_name") or "",
                (v.get("description") or "").split("\n[复核]")[0][:120],
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def _operations_csv(operations: list[dict]) -> bytes:
    """与本任务相关的审计留痕（task/结论维度的关键操作）。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["时间", "操作人", "动作", "资源类型", "资源ID", "详情"])
    for op in operations:
        w.writerow(
            [
                op.get("created_at") or "",
                op.get("username") or "",
                op.get("action") or "",
                op.get("resource_type") or "",
                op.get("resource_id") or "",
                (op.get("detail") or "")[:200],
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def build_evidence_zip(
    report: dict,
    report_md: str,
    report_json: str,
    operations: list[dict],
    meta: dict,
) -> bytes:
    """组装证据包 zip（纯函数）。meta 携带任务元信息（id/材料名/时间线）。"""
    files: dict[str, bytes] = {
        "审查报告.md": report_md.encode("utf-8"),
        "审查报告.json": report_json.encode("utf-8"),
        "结论生命周期.csv": _lifecycle_csv(report),
        "操作留痕.csv": _operations_csv(operations),
    }

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "task": meta,
        "files": {
            name: {"sha256": _sha256(data), "bytes": len(data)}
            for name, data in files.items()
        },
        "note": "本清单记录包内各文件的 SHA256，用于验证证据包完整性",
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", manifest_bytes)
    return buf.getvalue()


def collect_evidence(db: Session, task) -> tuple[dict, str, str, list[dict], dict]:
    """从 DB 与落盘文件组装证据包输入。调用方需先校验任务可导出。"""
    report_path = Path(task.report_path)
    report_md = report_path.with_suffix(".md").read_text(encoding="utf-8")
    report: dict = json.loads(report_path.read_text(encoding="utf-8"))
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    result_ids = [
        row[0]
        for row in db.query(ReviewResult.id)
        .filter(ReviewResult.task_id == task.id)
        .all()
    ]
    id_list = [str(task.id)] + [str(r) for r in result_ids]
    ops_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_type.in_(["task", "review_result"]),
            AuditLog.resource_id.in_(id_list),
        )
        .order_by(AuditLog.id)
        .all()
    )
    operations = [
        {
            "created_at": op.created_at.isoformat(timespec="seconds") if op.created_at else "",
            "username": op.username,
            "action": op.action,
            "resource_type": op.resource_type,
            "resource_id": op.resource_id,
            "detail": op.detail,
        }
        for op in ops_rows
    ]

    sign_offs = (
        db.query(TaskSignOff)
        .filter(TaskSignOff.task_id == task.id)
        .order_by(TaskSignOff.id)
        .all()
    )
    meta = {
        "task_id": task.id,
        "file_name": getattr(task, "file_name", None) or "",
        "status": task.status,
        "created_at": task.created_at.isoformat(timespec="seconds") if task.created_at else None,
        "completed_at": (
            task.completed_at.isoformat(timespec="seconds") if task.completed_at else None
        ),
        "sign_off_count": len(sign_offs),
    }
    return report, report_md, report_json, operations, meta
