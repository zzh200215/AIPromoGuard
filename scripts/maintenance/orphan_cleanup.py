"""孤儿行清洗（PR-7 前置）：逐表查外键悬空引用 → 删除/置空 → 审计留档。

为什么需要：给 9 张子表补外键前，库内可能存在孤儿行（如 review_results.task_id
指向已删任务、articles.regulation_id 指向不存在的法规），建 FK 时会被 MySQL
拒绝（errno 1452）。演示/开发数据策略：先清洗并留审计，再执行迁移。

清洗策略按「从属强度 + 列可空性」逐条定（见 FK_SPECS 的 orphan_action）：
- 强从属（NOT NULL 子列，如 results.task_id、links.rule_id、sign_offs.task_id）
  → **删除**孤儿行（行本身失去意义，保留只会污染统计）；
- 弱引用（可空列，如 created_by / rule_id / batch_id / regulation_id）
  → **置空**（保留行主体，只断开悬空指针）——与这些列上 FK 的 ON DELETE
  SET NULL 语义一致，清洗后的库状态与"父行先删"的因果一致。

用法：
    python scripts/maintenance/orphan_cleanup.py             # 扫描（只读，默认）
    python scripts/maintenance/orphan_cleanup.py --apply     # 执行清洗 + 写审计
审计：data/audits/orphan_cleanup_<YYYYMMDD_HHMMSS>.json

注意：本清单与迁移 `migrations/versions/*_add_foreign_keys.py` 内的冻结副本
必须一致——由 tests/unit/test_fk_specs.py 机械校验（防两处漂移）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.infrastructure.database.mysql import SessionLocal  # noqa: E402


@dataclass(frozen=True)
class FkSpec:
    """一条外键约束 + 其孤儿行清洗策略（迁移与运维共用同一张图）。"""

    child: str
    child_col: str
    parent: str
    parent_col: str = "id"
    ondelete: str = "SET NULL"  # CASCADE / SET NULL / RESTRICT
    orphan_action: str = "null"  # delete / null


# ---- 外键图（9 张子表 / 21 条约束）----
# 说明：多态列不建 FK——review_batches.source_id（source_type 决定指向）、
# audit_logs.resource_id（varchar 多态）、product_materials.document_id（指向文件非表）。
FK_SPECS: tuple[FkSpec, ...] = (
    # 内容层：条款强从属于法规
    FkSpec("articles", "regulation_id", "regulations", ondelete="CASCADE", orphan_action="delete"),
    # 审查链路：结果强从属于任务；规则/法规/条款为弱引用（法规废止后结论仍在）
    FkSpec("review_results", "task_id", "review_tasks", ondelete="CASCADE", orphan_action="delete"),
    FkSpec("review_results", "rule_id", "rules"),
    FkSpec("review_results", "regulation_id", "regulations"),
    FkSpec("review_results", "article_id", "articles"),
    FkSpec("review_results", "confirmed_by", "users"),
    # 任务：批次与创建人为弱引用
    FkSpec("review_tasks", "batch_id", "review_batches"),
    FkSpec("review_tasks", "created_by", "users"),
    # 批次：创建人弱引用
    FkSpec("review_batches", "created_by", "users"),
    # 规则-法规关联：关联行强从属于规则/法规
    FkSpec("rule_regulation_links", "rule_id", "rules", ondelete="CASCADE", orphan_action="delete"),
    FkSpec(
        "rule_regulation_links", "regulation_id", "regulations",
        ondelete="CASCADE", orphan_action="delete",
    ),
    FkSpec("rule_regulation_links", "article_id", "articles"),
    FkSpec("rule_regulation_links", "created_by", "users"),
    # 签发留痕：强从属于任务；签字人 NOT NULL → RESTRICT（有签字记录的用户不可硬删）
    FkSpec("task_sign_offs", "task_id", "review_tasks", ondelete="CASCADE", orphan_action="delete"),
    FkSpec("task_sign_offs", "user_id", "users", ondelete="RESTRICT", orphan_action="delete"),
    # 影响中心：法规更新/处罚案例为弱引用（依据失效后评估仍在）
    FkSpec("impact_assessments", "regulation_update_id", "regulation_updates"),
    FkSpec("impact_assessments", "penalty_case_id", "penalty_cases"),
    FkSpec("impact_assessments", "created_by", "users"),
    FkSpec("impact_assessments", "confirmed_by", "users"),
    # 通知：强从属于用户（用户没了通知无意义）
    FkSpec("notifications", "user_id", "users", ondelete="CASCADE", orphan_action="delete"),
    # 审计日志：用户弱引用（留痕优先，删除用户不删日志）
    FkSpec("audit_logs", "user_id", "users"),
)


def _orphan_where(spec: FkSpec) -> str:
    return (
        f"`{spec.child}`.`{spec.child_col}` IS NOT NULL "
        f"AND `{spec.parent}`.`{spec.parent_col}` IS NULL"
    )


def scan(db) -> list[dict]:
    """逐条统计孤儿行（只读）。"""
    out = []
    for spec in FK_SPECS:
        sql = (
            f"SELECT COUNT(*) FROM `{spec.child}` "
            f"LEFT JOIN `{spec.parent}` ON `{spec.child}`.`{spec.child_col}` = "
            f"`{spec.parent}`.`{spec.parent_col}` WHERE {_orphan_where(spec)}"
        )
        count = db.execute(text(sql)).scalar() or 0
        out.append({"spec": spec, "orphans": int(count)})
    return out


def apply_cleanup(db) -> list[dict]:
    """执行清洗（delete/null），返回明细（供审计落盘）。"""
    results = []
    for spec in FK_SPECS:
        where = (
            f"`{spec.child_col}` IS NOT NULL AND NOT EXISTS ("
            f"SELECT 1 FROM `{spec.parent}` p WHERE p.`{spec.parent_col}` = "
            f"`{spec.child}`.`{spec.child_col}`)"
        )
        sample_sql = f"SELECT `{spec.child_col}` FROM `{spec.child}` WHERE {where} LIMIT 20"
        sample = [r[0] for r in db.execute(text(sample_sql)).fetchall()]
        if not sample:
            results.append({**asdict(spec), "orphans": 0, "sample": [], "action_taken": None})
            continue
        if spec.orphan_action == "delete":
            cur = db.execute(text(f"DELETE FROM `{spec.child}` WHERE {where}"))
        else:
            cur = db.execute(
                text(f"UPDATE `{spec.child}` SET `{spec.child_col}` = NULL WHERE {where}")
            )
        results.append(
            {
                **asdict(spec),
                "orphans": len(sample) if len(sample) < 20 else cur.rowcount,
                "sample": sample,
                "action_taken": spec.orphan_action,
                "affected_rows": cur.rowcount,
            }
        )
    db.commit()
    return results


def _audit_path() -> Path:
    out_dir = ROOT / "data" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"orphan_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="孤儿行清洗（PR-7 前置）")
    parser.add_argument("--apply", action="store_true", help="执行清洗（默认仅扫描）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = scan(db)
        total = sum(r["orphans"] for r in rows)
        print(f"扫描：{len(rows)} 条约束，孤儿行合计 {total}")
        for r in rows:
            spec = r["spec"]
            mark = "!" if r["orphans"] else " "
            print(
                f" {mark} {spec.child}.{spec.child_col} → {spec.parent}.{spec.parent_col}"
                f"（{spec.ondelete}，action={spec.orphan_action}）：{r['orphans']} 行"
            )
        if not args.apply:
            print("\n（只读模式。执行清洗请加 --apply）")
            return 0
        if total == 0:
            print("\n无孤儿行，无需清洗。")
            return 0

        print("\n执行清洗 …")
        results = apply_cleanup(db)
        audit = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "mode": "apply",
            "total_orphans": total,
            "details": [
                {k: v for k, v in r.items() if k not in ("spec",)} for r in results
            ],
        }
        path = _audit_path()
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        for r in results:
            if r.get("action_taken"):
                print(
                    f"  ✓ {r['child']}.{r['child_col']}：{r['action_taken']} "
                    f"{r['affected_rows']} 行（样例 {r['sample'][:5]}）"
                )
        print(f"\n审计已落盘：{path.relative_to(ROOT)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
