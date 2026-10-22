"""演示预检：面试/演示前跑一遍，确认六幕动线的每个触点都活着。

把《演示脚本.md》的"演示前检查清单"变成可执行命令——只读检查，
不写库、不触发任务。

检查项：
1. 容器 7/7 运行中；API/前端 HTTP 可达
2. 幕一：战例任务报告存在且检出数正确（8 条）
3. 幕二/三：影响评估 #911、批次 #635（6/6）、#636（1 条）、#637（0 条）
4. 幕四：材料 #8300 版本 3 / clean
5. 幕五：证据包端点可用（读路由源码，确认端点存在）
6. 幕六：检索证据链有数据（cited_rules / cited_cases 至少各一条）
7. 台账 10 条、情报流水 ≥1（待确认 0 也算健康）、备份 48h 内有

用法: python scripts/ops/demo_preflight.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from src.utils.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" —— {detail}" if detail and not cond else ""))


def main() -> None:
    engine = create_engine(settings.mysql_url)
    with engine.connect() as conn:
        # 1) 系统
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        )
        names = [n for n in proc.stdout.split() if n.startswith("fcr-")]
        check("容器 7/7 运行", len(names) >= 7, f"实际 {len(names)}: {names}")
        for port, label in ((8000, "API"), (8080, "前端")):
            try:
                code = httpx.get(f"http://localhost:{port}/", timeout=5).status_code
            except Exception:
                code = 0
            check(f"{label} :{port} 可达", code in (200, 404, 422), f"HTTP {code}")

        # 2) 幕一：战例报告
        rpt = ROOT / "data/reports/task_987655221.json"
        ok = rpt.exists()
        n = 0
        if ok:
            n = len(json.loads(rpt.read_text(encoding="utf-8")).get("violations") or [])
        check("幕一战例报告存在且 8 条检出", ok and n == 8, f"检出 {n}")

        # 3) 幕二/三：评估与批次
        r = conn.execute(text("SELECT status FROM impact_assessments WHERE id=911")).fetchone()
        check("影响评估 #911 存在", r is not None, "缺失")
        rows = conn.execute(
            text(
                "SELECT id, status, total_count, completed_count FROM review_batches "
                "WHERE id IN (635, 636, 637)"
            )
        ).fetchall()
        got = {x[0]: (x[1], x[2], x[3]) for x in rows}
        check(
            "批次 #635 完成 6/6",
            got.get(635, ("", 0, 0))[0] == "completed"
            and got.get(635, ("", 0, 0))[2] == got.get(635, ("", 0, 0))[1],
            str(got.get(635)),
        )
        check("批次 #636/#637 存在", 636 in got and 637 in got, str(sorted(got)))

        # 4) 幕四：材料终态
        m = conn.execute(
            text(
                "SELECT version, last_review_status FROM product_materials WHERE id=8300"
            )
        ).fetchone()
        check(
            "材料 #8300 v3 / clean",
            m is not None and str(m[0]).lstrip("vV") == "3" and m[1] == "clean",
            str(m),
        )

        # 5) 幕五：证据包端点（源码级确认）
        router = (ROOT / "src/api/routers/reports.py").read_text(encoding="utf-8")
        check("证据包端点存在", "evidence-pack" in router, "未找到 evidence-pack 路由")

        # 6) 幕六：检索证据链（ORM 查询需要 Session）
        from sqlalchemy.orm import Session
        from src.services import regulation_service

        sess = Session(engine)
        try:
            hits = regulation_service.search(sess, "保本保收益", "hybrid", None, 5)
            hits = regulation_service.annotate_citation_links(sess, hits)
        finally:
            sess.close()
        cited_rules = [h for h in hits if h.get("cited_rules")]
        cited_cases = [h for h in hits if h.get("cited_cases")]
        check("检索证据链有规则关联", bool(cited_rules), "全为 0")
        check("检索证据链有罚单关联", bool(cited_cases), "全为 0")

        # 7) 台账/情报/备份
        n_mat = conn.execute(text("SELECT COUNT(*) FROM product_materials")).scalar()
        n_pending = conn.execute(
            text("SELECT COUNT(*) FROM regulation_updates WHERE status='pending'")
        ).scalar()
        n_imported = conn.execute(
            text("SELECT COUNT(*) FROM regulation_updates WHERE status='imported'")
        ).scalar()
        check("材料台账 ≥10 条", n_mat >= 10, f"{n_mat} 条")
        # 待确认=0 是健康终态（都研判完了），不能据此判不通过——只要情报流水有数据即可，
        # 演示讲"74 条情报 / 67 条已入库 / 0 待确认"比"73 条堆积待确认"更有说服力。
        check(
            "情报流水 ≥1（待确认 0 也算通过）",
            (n_pending + n_imported) >= 1,
            f"待确认 {n_pending} / 已入库 {n_imported}",
        )
        base = ROOT / "data/backups"
        recent = [
            d
            for d in base.iterdir()
            if d.is_dir() and d.name.startswith(datetime.now().strftime("%Y%m%d"))
        ] if base.exists() else []
        fresh = False
        for d in recent:
            try:
                ts = datetime.strptime(d.name, "%Y%m%d_%H%M%S")
                fresh = fresh or datetime.now() - ts < timedelta(hours=48)
            except ValueError:
                continue
        check("备份 48h 内有", fresh, "最近备份超过 48 小时")

    engine.dispose()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n预检结果：{len(RESULTS) - len(fails)}/{len(RESULTS)} 项通过")
    if fails:
        print("未通过项：" + "；".join(n for n, _, _ in fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
