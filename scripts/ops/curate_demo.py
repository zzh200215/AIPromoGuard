"""演示数据整备：让系统在面试演示里"像产品"，而不是像开发环境。

两类操作，分开执行、默认 dry-run：
1. 改名（安全、可回滚）：演示任务/材料/批次的技术化命名 → 产品化命名
   （如"演示材料-安稳盈FOF推文B"→"安稳盈 FOF 推文 B · 合规审查"，
   文档列 doc_5d6f7a02.txt → "安稳盈 FOF 推文 B.txt"）。变更映射写入
   data/eval/demo_rename_log.json，可据此回滚。
2. 清理（破坏性、需显式 --yes）：删除开发残留任务（【验证】/失败任务）
   及其审查结果。默认只列清单。

用法:
    python scripts/ops/curate_demo.py                     # dry-run：预览全部变更
    python scripts/ops/curate_demo.py --apply-rename      # 执行改名（可回滚）
    python scripts/ops/curate_demo.py --apply-delete --yes  # 执行清理（不可逆，先看清单）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import bindparam, create_engine, text  # noqa: E402
from src.utils.config import settings  # noqa: E402

LOG_PATH = Path("data/eval/demo_rename_log.json")

# ---- 改名计划（产品化命名）----
TASK_RENAMES: dict[int, tuple[str, str]] = {
    # 战例（真实软文）
    987655221: ("公募基金长跑业绩盘点 · 营销材料审查", "公募长跑成绩单盘点（腾讯新闻）.txt"),
    # 闭环复审 6 份（批次 #635）
    987655344: ("安稳盈 FOF 推文 B · 合规审查", "安稳盈 FOF 推文 B.txt"),
    987655345: ("稳健回报混合基金单页 A · 合规审查", "稳健回报混合基金单页 A.txt"),
    987655346: ("聚利稳选海报 C · 合规审查", "聚利稳选海报 C.txt"),
    987655347: ("启航混合直播话术 E · 合规审查", "启航混合直播话术 E.txt"),
    987655348: ("成长先锋股票基金单页 D · 合规审查", "成长先锋股票基金单页 D.txt"),
    987655349: ("远见精选推文 F · 合规审查", "远见精选推文 F.txt"),
    # 两轮整改复测
    987655350: ("安稳盈 FOF 推文 B · 整改复测（第 1 轮）", "安稳盈 FOF 推文 B · 整改版 v2.txt"),
    987655351: ("安稳盈 FOF 推文 B · 整改复测（第 2 轮）", "安稳盈 FOF 推文 B · 整改版 v3.txt"),
}

MATERIAL_RENAMES: dict[int, str] = {
    8299: "稳健回报混合基金单页 A",
    8300: "安稳盈 FOF 推文 B",
    8301: "聚利稳选海报 C",
    8302: "成长先锋股票基金单页 D",
    8303: "启航混合直播话术 E",
    8304: "远见精选推文 F",
    8305: "指数增强基金单页 G",
    8306: "中证 500 物料 H",
    8307: "红利低波海报 I",
    8308: "量化对冲推文 J",
}

BATCH_RENAMES: dict[int, str] = {
    635: "复审批次 · 公募产品营销物料申报要求补充通知（演示）",
    636: "整改复测 · 安稳盈 FOF 推文 B（第 1 轮）",
    637: "整改复测 · 安稳盈 FOF 推文 B（第 2 轮）",
    170: "复审批次 · 公募产品营销物料申报要求补充通知（演示）",
    171: "整改复测 · 安稳盈 FOF 推文 B",
    161: "批次 03",
}

# 删除候选：开发验证任务 + 失败任务（审查结果一并删除）
DELETE_NAME_PREFIX = "【验证】"


# 演示保留集：产品化任务（删除历史时唯一的白名单）
KEEP_TASK_IDS = {
    987655221,  # 战例：公募基金长跑业绩盘点
    987655344, 987655345, 987655346, 987655347, 987655348, 987655349,  # 闭环复审 6 份
    987655350, 987655351,  # 两轮整改复测
}
KEEP_BATCH_IDS = {635, 636, 637}  # 闭环批次


def _prune_history(conn, yes: bool) -> None:
    """删除 KEEP 之外的全部历史任务与批次（开发期数据），先落审计清单。"""
    tasks = conn.execute(
        text("SELECT id, task_name, status FROM review_tasks ORDER BY id")
    ).fetchall()
    drop_tasks = [r for r in tasks if r[0] not in KEEP_TASK_IDS]
    batches = conn.execute(
        text("SELECT id, batch_name FROM review_batches ORDER BY id")
    ).fetchall()
    drop_batches = [r for r in batches if r[0] not in KEEP_BATCH_IDS]
    print("== 历史裁剪（破坏性）==")
    print(f"  删除任务 {len(drop_tasks)} 条（保留 {len(tasks) - len(drop_tasks)} 条白名单）")
    print(f"  删除批次 {len(drop_batches)} 个（保留 {sorted(KEEP_BATCH_IDS)}）")
    for r in drop_tasks[:5]:
        print(f"    任务 #{r[0]} [{r[2]}] {str(r[1])[:40]}")
    print("    ……")
    if not yes:
        print("  需要 --yes 确认")
        return
    log_path = Path("data/eval/history_prune_20261019.json")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(
            {
                "tasks": [{"id": r[0], "task_name": r[1], "status": r[2]} for r in drop_tasks],
                "batches": [{"id": r[0], "batch_name": r[1]} for r in drop_batches],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    ids = [r[0] for r in drop_tasks]
    if ids:
        conn.execute(
            text("DELETE FROM review_results WHERE task_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )
        conn.execute(
            text("DELETE FROM review_tasks WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )
    bids = [r[0] for r in drop_batches]
    if bids:
        conn.execute(
            text("DELETE FROM review_batches WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": bids},
        )
    conn.commit()
    print(f"  已删除 {len(ids)} 任务 / {len(bids)} 批次（审计清单 {log_path}）")


def main() -> None:
    apply_rename = "--apply-rename" in sys.argv
    apply_delete = "--apply-delete" in sys.argv
    apply_prune = "--apply-prune" in sys.argv
    yes = "--yes" in sys.argv
    engine = create_engine(settings.mysql_url)
    with engine.connect() as conn:
        # ---- 1) 改名预览/执行 ----
        print("== 改名计划 ==")
        changes: list[dict] = []
        for tid, (new_task, new_doc) in TASK_RENAMES.items():
            r = conn.execute(
                text("SELECT task_name, document_name FROM review_tasks WHERE id=:i"), {"i": tid}
            ).fetchone()
            if not r:
                print(f"  #任务 {tid} 不存在，跳过")
                continue
            changes.append(
                {"type": "task", "id": tid, "old": [r[0], r[1]], "new": [new_task, new_doc]}
            )
            print(f"  任务 #{tid}: {r[0][:26]} -> {new_task[:30]} | 文档: {r[1]} -> {new_doc}")
        for mid, new_name in MATERIAL_RENAMES.items():
            r = conn.execute(
                text("SELECT name FROM product_materials WHERE id=:i"), {"i": mid}
            ).fetchone()
            if not r:
                continue
            changes.append({"type": "material", "id": mid, "old": [r[0]], "new": [new_name]})
            print(f"  材料 #{mid}: {r[0]} -> {new_name}")
        for bid, new_name in BATCH_RENAMES.items():
            r = conn.execute(
                text("SELECT batch_name FROM review_batches WHERE id=:i"), {"i": bid}
            ).fetchone()
            if not r:
                continue
            changes.append({"type": "batch", "id": bid, "old": [r[0]], "new": [new_name]})
            print(f"  批次 #{bid}: {str(r[0])[:34]} -> {new_name}")

        # ---- 2) 删除候选 ----
        failed = conn.execute(
            text("SELECT id, task_name, status FROM review_tasks WHERE status='failed' ORDER BY id")
        ).fetchall()
        verify = conn.execute(
            text(
                "SELECT id, task_name, status FROM review_tasks "
                "WHERE task_name LIKE :p ORDER BY id"
            ),
            {"p": f"{DELETE_NAME_PREFIX}%"},
        ).fetchall()
        print("\n== 清理候选（破坏性，需 --apply-delete --yes）==")
        print(f"  失败任务 {len(failed)} 个；验证任务 {len(verify)} 个")
        for r in verify:
            print(f"    验证任务 #{r[0]} [{r[2]}] {str(r[1])[:40]}")
        for r in failed[:6]:
            print(f"    失败任务 #{r[0]} {str(r[1])[:44]}")
        print(f"    ……共 {len(failed)} 个失败任务")

        if apply_rename and changes:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            LOG_PATH.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
            for c in changes:
                if c["type"] == "task":
                    conn.execute(
                        text("UPDATE review_tasks SET task_name=:n, document_name=:d WHERE id=:i"),
                        {"n": c["new"][0], "d": c["new"][1], "i": c["id"]},
                    )
                elif c["type"] == "material":
                    conn.execute(
                        text("UPDATE product_materials SET name=:n WHERE id=:i"),
                        {"n": c["new"][0], "i": c["id"]},
                    )
                else:
                    conn.execute(
                        text("UPDATE review_batches SET batch_name=:n WHERE id=:i"),
                        {"n": c["new"][0], "i": c["id"]},
                    )
            conn.commit()
            print(f"\n改名完成：{len(changes)} 项（回滚映射已存 {LOG_PATH}）")

        if apply_prune:
            _prune_history(conn, yes)

        if apply_delete:
            if not yes:
                print("\n删除需要显式 --yes 确认（先看上面的清单）")
            else:
                ids = [r[0] for r in failed] + [r[0] for r in verify]
                if ids:
                    stmt_res = text(
                        "DELETE FROM review_results WHERE task_id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True))
                    stmt_task = text(
                        "DELETE FROM review_tasks WHERE id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True))
                    conn.execute(stmt_res, {"ids": ids})
                    conn.execute(stmt_task, {"ids": ids})
                    conn.commit()
                print(f"\n已删除 {len(ids)} 个任务及其审查结果（报告文件保留在 data/reports）")
    engine.dispose()


if __name__ == "__main__":
    main()
