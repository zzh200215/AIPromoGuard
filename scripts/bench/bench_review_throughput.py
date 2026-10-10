"""审查任务并发吞吐基线：线程池并发 5/10/20 任务，吞吐 + 端到端延迟分布。

口径（详见 docs/benchmark.md §6「性能基线」）：
- **服务级进程内直调**：真实 `start_review`（submit 进 review_service._executor，
  max_workers=2 真实排队）→ 测系统自身处理能力，跳过 HTTP 层。
- **默认 offline**：`settings.dashscope_api_key` 置空 → LLM 节点走官方降级路径
  跳过（确定性、可重复）。`--with-llm` 测全链路（含 LLM 调用，受网关限流/额度
  影响，只作参考值、消耗额度）。
- **默认屏蔽图谱查询**（--with-graph 保留）：默认部署无 Neo4j，屏蔽可消除
  冷却到期后的 ~2s 周期性重探噪声，口径 = "无图谱部署的确定性形态"。
- 造数：固定演示材料文案；任务名带 `[bench]` 标记；每档 repeat 轮（默认 3）
  合并统计——单轮 wall 仅 ~1s，多轮合并降低调度噪声放大效应。
- 每档独立：准备 N 任务 → 线程池并发 N 提交 → 轮询至全部终态 → 统计 → 清理
  （结论/任务/上传文件/checkpoint 线程 delete_thread）。

用法（项目根执行）：
    python scripts/bench/bench_review_throughput.py
    python scripts/bench/bench_review_throughput.py --levels 5,10,20 \
        --json data/bench/throughput.json
    python scripts/bench/bench_review_throughput.py --levels 5 --with-llm  # 全链路（消耗额度）
"""

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from _common import pct_stats  # noqa: E402
from src.core.agents.runtime import thread_id_for_task  # noqa: E402
from src.core.llm.client import get_llm  # noqa: E402
from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.models import ReviewResult, ReviewTask, User  # noqa: E402
from src.services import review_service  # noqa: E402
from src.services.review_service import start_review  # noqa: E402
from src.utils.config import settings  # noqa: E402

# 固定基准材料：含明确违规表述（保本保息/稳赚不赔/预期年化收益）触发规则命中
# 与混合检索，覆盖全链路除 LLM 外的全部阶段。
_BENCH_MATERIAL = (
    "稳健回报混合型基金 产品宣传材料（性能基准）\n\n"
    "本产品保本保息，稳赚不赔，预期年化收益 12%，限时抢购，扫码立即申购。\n\n"
    "本产品风险极低，适合所有投资者，历史收益稳健增厚。\n\n"
    "基金管理人承诺收益，投资零风险，收益有保障。\n\n"
    "本产品由资深团队管理，过往业绩优秀，未来收益可期。\n\n"
    "投资有风险，入市需谨慎。过往业绩不预示未来表现。\n\n"
    "投资者在投资本产品前应认真阅读基金合同与招募说明书，"
    "了解产品风险收益特征，根据自身风险承受能力谨慎决策。\n"
)

# 终态：completed/failed 为完成；awaiting_review 为 HIL 中断（默认配置不会出现，
# 兜底识别避免轮询空转超时）
_TERMINAL = {"completed", "failed", "awaiting_review"}


def _prepare_tasks(db, admin_id: int, n: int) -> list[int]:
    """准备 n 个待审任务：材料文件写入 upload 目录 + ReviewTask 行（pending）。"""
    upload_dir = Path(settings.upload_dir) / str(admin_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    ids: list[int] = []
    for i in range(n):
        fname = f"bench_{stamp}_{i:03d}.txt"
        fpath = upload_dir / fname
        fpath.write_text(_BENCH_MATERIAL, encoding="utf-8")
        task = ReviewTask(
            task_name=f"[bench] {stamp}-{i:03d}",
            document_name=fname,
            document_path=str(fpath),
            document_type="宣传材料",
            domain="fund",
            status="pending",
            created_by=admin_id,
        )
        db.add(task)
        db.flush()
        ids.append(task.id)
    db.commit()
    return ids


def _cleanup(db, task_ids: list[int]) -> None:
    """清理：checkpoint 线程 + 结论 + 任务 + 上传文件/报告（keep 模式不调用）。"""
    from src.infrastructure.database.langgraph_saver import MySQLCheckpointSaver

    saver = MySQLCheckpointSaver()
    for tid in task_ids:
        saver.delete_thread(thread_id_for_task(tid))

    rows = db.query(ReviewTask).filter(ReviewTask.id.in_(task_ids)).all()
    paths = [
        Path(p)
        for t in rows
        for p in (t.document_path, t.report_path)
        if p
    ]
    db.query(ReviewResult).filter(ReviewResult.task_id.in_(task_ids)).delete(
        synchronize_session=False
    )
    db.query(ReviewTask).filter(ReviewTask.id.in_(task_ids)).delete(synchronize_session=False)
    db.commit()
    for p in paths:
        p.unlink(missing_ok=True)


def _run_level_once(db, admin_id: int, level: int, timeout: int, keep: bool) -> dict:
    """跑一轮：准备 level 个任务 → 并发提交 → 轮询至全部终态 → 统计（→ 清理）。"""
    task_ids = _prepare_tasks(db, admin_id, level)
    done_at: dict[int, float] = {}
    try:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=level) as pool:
            list(pool.map(start_review, task_ids))

        deadline = time.perf_counter() + timeout
        while True:
            rows = (
                db.query(ReviewTask.id, ReviewTask.status)
                .filter(ReviewTask.id.in_(task_ids))
                .all()
            )
            # 关键：MySQL REPEATABLE READ 下同一事务内快照不变，若不结束事务，
            # 轮询永远读到首次快照（execute_review 在其他连接的提交不可见）——
            # 每次读完即释放快照，下一轮重新读取最新状态。
            db.rollback()
            for tid, st in rows:
                if st in _TERMINAL and tid not in done_at:
                    done_at[tid] = time.perf_counter()
            if len(done_at) == len(task_ids):
                break
            if time.perf_counter() > deadline:
                pending = [t for t in task_ids if t not in done_at]
                raise TimeoutError(f"档位 {level}: 超时 {timeout}s，未终态任务 {pending}")
            # 轮询粒度 50ms：完成时刻检测误差直接进入端到端延迟统计，
            # 亚秒任务下 0.3s 粒度会引入 ±20%+ 噪声（PR-9 实测）。
            time.sleep(0.05)

        wall_s = max(done_at.values()) - t0
        e2e_ms = [(done_at[t] - t0) * 1000 for t in task_ids]

        rows = db.query(ReviewTask).filter(ReviewTask.id.in_(task_ids)).all()
        statuses = Counter(t.status for t in rows)
        # 处理时长 = 图内节点耗时总和（stages.cost_ms，毫秒精度）。
        # 不用 started_at/completed_at 差值：MySQL DATETIME 秒级精度，
        # 亚秒任务恒为 0（PR-9 实测）。
        proc_ms = []
        for t in rows:
            stages = t.stages or {}
            total = sum(
                int(s.get("cost_ms") or 0) for s in stages.values() if isinstance(s, dict)
            )
            if total:
                proc_ms.append(float(total))
        findings = (
            db.query(ReviewResult)
            .filter(ReviewResult.task_id.in_(task_ids))
            .count()
        )
        db.rollback()

        return {
            "level": level,
            "tasks": len(task_ids),
            "ok": statuses.get("completed", 0),
            "failed": statuses.get("failed", 0),
            "awaiting_review": statuses.get("awaiting_review", 0),
            "wall_s": round(wall_s, 2),
            "throughput_per_min": round(len(task_ids) / wall_s * 60, 2),
            "findings": findings,
            "e2e_samples": e2e_ms,
            "proc_samples": proc_ms,
        }
    finally:
        if keep:
            print(f"    --keep：保留本档任务 {task_ids}")
        else:
            _cleanup(db, task_ids)


def _run_level(db, admin_id: int, level: int, timeout: int, keep: bool, repeat: int) -> dict:
    """跑一档（repeat 轮合并）：多轮样本合并降低调度噪声对指标的放大效应。

    单轮 wall 仅 ~1s（亚秒任务 × 少量样本），吞吐 = 任务数/墙钟 对调度抖动
    高度敏感（PR-9 实测单轮偏差 10%+）——多轮合并（吞吐按总墙钟、延迟按合并
    样本）是基线可重复性的关键。
    """
    rounds = []
    all_e2e: list[float] = []
    all_proc: list[float] = []
    for _ in range(repeat):
        r = _run_level_once(db, admin_id, level, timeout, keep)
        all_e2e.extend(r.pop("e2e_samples"))
        all_proc.extend(r.pop("proc_samples"))
        rounds.append(r)
    total_tasks = sum(r["tasks"] for r in rounds)
    total_wall = sum(r["wall_s"] for r in rounds)
    return {
        "level": level,
        "repeat": repeat,
        "tasks": total_tasks,
        "ok": sum(r["ok"] for r in rounds),
        "failed": sum(r["failed"] for r in rounds),
        "awaiting_review": sum(r["awaiting_review"] for r in rounds),
        "wall_s": round(total_wall, 2),
        "throughput_per_min": round(total_tasks / total_wall * 60, 2),
        "e2e_ms": pct_stats(all_e2e),
        "process_ms": pct_stats(all_proc),  # 图内节点耗时（不含排队）
        "findings": sum(r["findings"] for r in rounds),
        "rounds": rounds,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="审查任务并发吞吐基线")
    ap.add_argument("--levels", default="5,10,20", help="并发档位（默认 5,10,20）")
    ap.add_argument("--with-llm", action="store_true", help="全链路模式（含 LLM；消耗额度）")
    ap.add_argument("--timeout", type=int, default=900, help="每档等待上限秒数（默认 900）")
    ap.add_argument("--warmup", type=int, default=1, help="预热任务数（不计入统计，默认 1）")
    ap.add_argument("--repeat", type=int, default=3, help="每档重复轮数（合并统计，默认 3）")
    ap.add_argument("--keep", action="store_true", help="保留任务数据（调试用，默认跑完即清）")
    ap.add_argument(
        "--with-graph",
        action="store_true",
        help="保留图谱查询（默认屏蔽：默认部署无 Neo4j，屏蔽可消除 ~2s 周期性重探噪声）",
    )
    ap.add_argument("--json", dest="json_path", default=None, help="结果写入 JSON 文件路径")
    args = ap.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    if not args.with_graph:
        # 屏蔽图谱查询：默认部署无 Neo4j 时，客户端靠 60s 冷却快速失败，
        # 但冷却到期后首个查询仍付 driver 重探 ~2s，周期性地落在个别任务上
        # （吞吐/长尾噪声，PR-9 实测）。基准口径 = "无图谱部署的确定性形态"——
        # 直接短路 graph_service 的查询入口，全程零重探。
        import src.services.graph_service as _graph

        _graph.run_cypher = lambda *a, **k: []  # type: ignore[assignment]
        print("图谱查询已屏蔽（--with-graph 可保留）")

    if args.with_llm:
        if get_llm() is None:
            raise SystemExit("live 模式需要配置可用的网关 Key（.env DASHSCOPE_API_KEY）")
        mode = "live"
        print("模式: live（全链路含 LLM；受网关限流/额度影响，作参考值）")
    else:
        settings.dashscope_api_key = ""
        assert get_llm() is None, "offline 模式要求 LLM 不可用（未配置 key）"
        mode = "offline"
        print("模式: offline（LLM 节点官方降级跳过；确定性口径，可重复）")

    db = SessionLocal()
    try:
        admin_id = db.query(User.id).filter(User.username == "admin").scalar()
        db.rollback()  # 释放快照，后续轮询读最新提交
        if admin_id is None:
            raise SystemExit("未找到 admin 用户（先跑 scripts/init_data/init_admin.py）")
        worker_limit = review_service._executor._max_workers  # noqa: SLF001 基准对象即该常量
        print(f"服务端并发上限: _executor max_workers={worker_limit}")

        # 预热队列探测（单线程）：首次探测有 ~2s 开销，预热避免首个档位抖动
        review_service._use_celery()  # noqa: SLF001 预热内部探测（锁内单线程，安全）

        if args.warmup:
            print(f"[warmup] {args.warmup} 个任务（剔除模型加载/连接冷启动，不计入统计）")
            _run_level_once(db, admin_id, args.warmup, args.timeout, keep=args.keep)

        results = []
        for level in levels:
            r = _run_level(
                db, admin_id, level, args.timeout, keep=args.keep, repeat=args.repeat
            )
            results.append(r)
            print(
                f"  档位 {level:>2}: 完成 {r['ok']}/{r['tasks']}"
                f"（failed {r['failed']}）| 吞吐 {r['throughput_per_min']} 任务/分钟"
                f" | 端到端 p50={r['e2e_ms']['p50_ms']}ms p95={r['e2e_ms']['p95_ms']}ms"
                f" | 处理 p50={r['process_ms']['p50_ms']}ms | 结论 {r['findings']} 条"
                f"（{r['repeat']} 轮合并）"
            )

        if args.json_path:
            out = {
                "bench": "review_throughput",
                "mode": mode,
                "worker_limit": worker_limit,
                "levels": results,
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            p = Path(args.json_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  已写入 {p}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
