"""罚单-法规关联回写：把 Neo4j 图谱的多跳关系落到 MySQL penalty_cases.related_regulations。

背景：检索页证据链（regulation_service.annotate_citation_links）读 MySQL 的
related_regulations，但该列只有 2/68 有值——种子只写了直接边
BASED_ON_REGULATION(2 条)。图谱里真正的关联在多跳路径上：

    PenaltyCase -[:INVOLVES_VIOLATION]-> ViolationPattern
                <-[:VIOLATES]- Article <-[:HAS_ARTICLE]- Regulation

（2026-10-16 实测：60 罚单 × 21 法规；图谱节点 id 与 MySQL 主键一一对应，
校验 0 缺失。）

用法:
    python scripts/maintenance/backfill_case_reg_links.py            # dry-run：只打印计划
    python scripts/maintenance/backfill_case_reg_links.py --apply    # 实际写库

语义：并集合并（保留已有 + 追加图谱新知），幂等——重复运行无变更。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.neo4j_client import run_cypher_strict
from src.utils.logger import get_logger

logger = get_logger(__name__)

_GRAPH_PATH = (
    "MATCH (pc:PenaltyCase)-[:INVOLVES_VIOLATION]->(vp:ViolationPattern) "
    "<-[:VIOLATES]-(art:Article) <-[:HAS_ARTICLE]-(reg:Regulation) "
    "RETURN pc.id AS pc_id, collect(DISTINCT reg.id) AS reg_ids"
)


def _coerce_reg_ids(existing) -> set[int]:
    """把 related_regulations 的各种历史形态归一为 int 集合。

    实测库里存在双重编码（JSON 列里存了字符串 '["22"]'）——2026-10-16 dry-run 撞上；
    解析失败/垃圾值一律当空处理（宁缺毋错，图谱新知会补全）。
    """
    if existing is None:
        return set()
    if isinstance(existing, str):
        s = existing.strip()
        if not s:
            return set()
        try:
            existing = json.loads(s)
        except json.JSONDecodeError:
            return set()
    if isinstance(existing, list | tuple):
        out: set[int] = set()
        for x in existing:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return {int(existing)}
    except (TypeError, ValueError):
        return set()


def merge_reg_ids(existing: list | None, new_ids: list[int]) -> list[int]:
    """并集合并（去重 + 升序），兼容旧数据里的字符串/双重编码形态。"""
    return sorted(_coerce_reg_ids(existing) | {int(x) for x in new_ids})


def fetch_graph_links() -> dict[int, set[int]]:
    """图谱多跳路径 → {罚单 id: 关联法规 id 集合}。"""
    rows = run_cypher_strict(_GRAPH_PATH)
    links: dict[int, set[int]] = {}
    for r in rows:
        links.setdefault(int(r["pc_id"]), set()).update(int(x) for x in r["reg_ids"])
    return links


def run(apply: bool) -> None:
    from sqlalchemy import text
    from src.infrastructure.database.mysql import engine

    graph_links = fetch_graph_links()
    logger.info("图谱路径覆盖 %s 个罚单", len(graph_links))

    with engine.connect() as conn:
        case_rows = conn.execute(
            text("SELECT id, related_regulations FROM penalty_cases")
        ).fetchall()
        valid_cases = {r[0] for r in case_rows}
        valid_regs = {r[0] for r in conn.execute(text("SELECT id FROM regulations"))}

    current = {r[0]: (r[1] or []) for r in case_rows}

    plan: dict[int, list[int]] = {}
    skipped_case = skipped_reg = 0
    for pid, reg_ids in graph_links.items():
        if pid not in valid_cases:
            skipped_case += 1
            continue
        known = reg_ids & valid_regs
        skipped_reg += len(reg_ids) - len(known)
        merged = merge_reg_ids(current.get(pid), known)
        if merged != sorted(_coerce_reg_ids(current.get(pid))):
            plan[pid] = merged

    added_total = sum(len(m) - len(current.get(pid) or []) for pid, m in plan.items())
    mode = "否" if apply else "是"
    print(f"图谱覆盖 {len(graph_links)} 罚单（MySQL 缺失罚单 {skipped_case}）")
    print(
        f"法规引用缺失 {skipped_reg}；计划变更 {len(plan)} 个罚单，"
        f"新增关联 {added_total} 条（dry-run={mode}）"
    )
    for pid in sorted(plan)[:8]:
        old = sorted(_coerce_reg_ids(current.get(pid)))
        print(f"  #{pid}: {old} -> {plan[pid]}")
    if len(plan) > 8:
        print(f"  ... 其余 {len(plan) - 8} 个省略")

    if not apply:
        print("dry-run 结束（加 --apply 写库）")
        return


    with engine.begin() as conn:
        for pid, merged in plan.items():
            conn.execute(
                text("UPDATE penalty_cases SET related_regulations = :regs WHERE id = :pid"),
                {"regs": json.dumps(merged), "pid": pid},
            )
    print(f"已写库：{len(plan)} 个罚单更新完成")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
