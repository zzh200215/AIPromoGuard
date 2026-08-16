"""方向④：真实人工复核 → 评估集导出管线。

把系统里真实人工复核结果（confirmed_by>0，排除系统自动确认）导出为
scripts/evaluate/real_cases.json（eval_cases.json 同格式），让基准集随真实使用增长
——这就是"真实标注集替换合成样本"的机制：合成样本是起步的 eval_cases.json，
真实复核数据积累后导出到这里，可人工合并或单独 --cases real_cases.json 跑评估。

分组口径（按 review_task 聚合）:
- 全 confirmed   → 正例案例：原文 + ground_truth(每条 confirmed 的命中片段 + 规则名)
- 全 false_positive → 负面案例：ground_truth=[]（系统在该文档上误触发，测不应命中）
- 混合（同任务既有 confirmed 又有 FP）→ 跳过并告警（当前 eval 格式无法表达）

安全网: 排除 description 带测试标记（"[复核] 测试人工复核" / "E2E" / "e2e"）的记录，
与数据清理口径一致，防止开发期噪声污染真实标注集。

用法:
    python scripts/evaluate/export_labels.py [--out scripts/evaluate/real_cases.json]
    python scripts/evaluate/evaluate.py --engine rule --cases scripts/evaluate/real_cases.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal

DEFAULT_OUT = Path(__file__).resolve().parent / "real_cases.json"
# 与数据清理一致的测试标记（人工复核 notes，见 direction③ 数据清理）
_TEST_MARKERS = ("测试人工复核", "E2E", "e2e")


def _is_test_row(description: str | None) -> bool:
    return any(m in (description or "") for m in _TEST_MARKERS)


def _read_document(document_path: str | None) -> str | None:
    """按 DB 里的 document_path 读源文档原文（兼容 \\ 分隔符，相对仓库根解析）。"""
    if not document_path:
        return None
    p = Path(document_path.replace("\\", "/"))
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def export_labels() -> dict:
    """查询真实人工复核并组装为 eval_cases 结构。"""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT rr.task_id, rr.original_text, rr.status, rr.risk_level,
                       rr.description, r.rule_name, r.domain AS rule_domain,
                       t.document_path, t.domain AS task_domain
                FROM review_results rr
                LEFT JOIN rules r        ON r.id = rr.rule_id
                LEFT JOIN review_tasks t ON t.id = rr.task_id
                WHERE rr.confirmed_by > 0
                ORDER BY rr.task_id
                """
            )
        ).fetchall()
    finally:
        db.close()

    by_task: dict[int, dict] = defaultdict(
        lambda: {"confirmed": [], "false_positive": [],
                 "document_path": None, "rule_domain": None, "task_domain": None}
    )
    skipped_test = skipped_mixed = skipped_unreadable = 0
    for row in rows:
        task_id, original_text, status, risk_level, description = row[:5]
        rule_name, rule_domain, doc_path, task_domain = row[5:]
        if _is_test_row(description):
            skipped_test += 1
            continue
        task = by_task[task_id]
        task["document_path"] = task["document_path"] or doc_path
        task["rule_domain"] = task["rule_domain"] or rule_domain
        task["task_domain"] = task["task_domain"] or task_domain
        bucket = task["confirmed"] if status == "confirmed" else task["false_positive"]
        bucket.append(
            {"text": original_text, "rule_name": rule_name or "", "risk_level": risk_level or ""}
        )

    cases = []
    for task_id in sorted(by_task):
        t = by_task[task_id]
        text_body = _read_document(t["document_path"])
        if not text_body:
            skipped_unreadable += 1
            continue
        if t["confirmed"] and t["false_positive"]:
            skipped_mixed += 1
            continue
        domain = t["task_domain"] or t["rule_domain"] or "unknown"
        cases.append(
            {
                "id": f"real_{task_id}",
                "domain": domain,
                "text": text_body,
                "ground_truth": t["confirmed"],  # 全 FP 时为空列表 → 负面案例
            }
        )

    if not cases:
        print("未导出任何案例：当前无真实人工复核数据（confirmed_by>0）。")
    else:
        print(f"导出 {len(cases)} 个案例（confirmed 正例 + FP 负面）。")
    if skipped_test or skipped_mixed or skipped_unreadable:
        print(
            "跳过: "
            f"测试标记 {skipped_test} / 混合任务 {skipped_mixed} / "
            f"文档不可读 {skipped_unreadable}"
        )
    return {"cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = export_labels()
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入: {args.out}（{len(data['cases'])} 案例）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
