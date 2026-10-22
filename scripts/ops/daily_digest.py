"""每日运转摘要：一眼看清"系统今天干了什么、有没有异常"。

背景（30 天里程碑的每日 5 分钟仪式）：系统常驻后需要低成本观测——
心跳有没有跳、任务跑了多少、有没有失败、备份在不在、待确认法规堆积没。
本脚本只读（不写库、不触发任何任务），可安全地每天跑一次。

用法:
    python scripts/ops/daily_digest.py          # 中文摘要
    python scripts/ops/daily_digest.py --json   # 机器可读（供后续接入驾驶舱）
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 摘要要干净：关掉 SQLAlchemy 的 SQL echo（在 main 里设置，避开应用 logger 的初始化覆盖）
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_TS_RE = re.compile(r"\d{8}_\d{6}")


def _section(name, fn, default=None):
    """单节失败不拖垮整份摘要。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("摘要节 %s 失败: %s", name, exc)
        return default


def _containers() -> dict:
    proc = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=15,
    )
    rows = [ln.split("\t") for ln in proc.stdout.splitlines() if ln.strip()]
    fcr = [(n, s) for n, s in rows if n.startswith("fcr-")]
    return {"running": sum(1 for _, s in fcr if s.startswith("Up")), "total": len(fcr),
            "detail": [f"{n}: {s}" for n, s in fcr]}


def _db_digest() -> dict:
    from sqlalchemy import create_engine, text
    from src.utils.config import settings

    # 自建无 echo 引擎：应用 engine 带 SQL echo，摘要输出要保持干净
    engine = create_engine(settings.mysql_url)

    today = datetime.combine(date.today(), time.min)
    with engine.connect() as conn:
        out = {}
        out["tasks_completed_today"] = conn.execute(
            text(
                "SELECT COUNT(*) FROM review_tasks "
                "WHERE status='completed' AND completed_at >= :t"
            ),
            {"t": today},
        ).scalar()
        out["tasks_failed_today"] = conn.execute(
            text("SELECT COUNT(*) FROM review_tasks WHERE status='failed' AND created_at >= :t"),
            {"t": today},
        ).scalar()
        out["violations_today"] = conn.execute(
            text(
                "SELECT COUNT(*) FROM review_results r JOIN review_tasks t ON t.id=r.task_id "
                "WHERE t.status='completed' AND t.completed_at >= :t"
            ),
            {"t": today},
        ).scalar()
        out["regs_pending"] = conn.execute(
            text("SELECT COUNT(*) FROM regulation_updates WHERE status='pending'")
        ).scalar()
        out["regs_new_today"] = conn.execute(
            text("SELECT COUNT(*) FROM regulation_updates WHERE created_at >= :t"), {"t": today}
        ).scalar()
        last = conn.execute(
            text("SELECT MAX(created_at) FROM regulation_updates")
        ).scalar()
        out["last_reg_at"] = str(last) if last else None
        out["penalties"] = conn.execute(text("SELECT COUNT(*) FROM penalty_cases")).scalar()
        out["materials"] = dict(
            conn.execute(
                text(
                    "SELECT COALESCE(last_review_status,'未审'), COUNT(*) "
                    "FROM product_materials GROUP BY last_review_status"
                )
            ).fetchall()
        )
        out["zombie_pending"] = conn.execute(
            text("SELECT COUNT(*) FROM review_tasks WHERE status='pending'")
        ).scalar()
        return out


def _latest_backup(base: Path | None = None) -> dict | None:
    base = base or Path("data/backups")
    if not base.exists():
        return None
    dirs = sorted(d for d in base.iterdir() if d.is_dir() and _TS_RE.fullmatch(d.name))
    if not dirs:
        return None
    latest = dirs[-1]
    size = sum(f.stat().st_size for f in latest.rglob("*") if f.is_file())
    # 完整性：优先读 manifest.json；老备份按文件推断
    manifest = latest / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            components = data.get("components") or {}
            missing = [k for k, v in components.items() if not (v or {}).get("ok")]
            return {
                "name": latest.name,
                "size_mb": round(size / 1024 / 1024, 1),
                "count": len(dirs),
                "missing": missing,
                "complete": not missing,
            }
        except (OSError, ValueError):
            pass
    expected = {"mysql": "mysql.sql", "neo4j": "neo4j.json", "uploads": "uploads"}
    missing = [k for k, f in expected.items() if not (latest / f).exists()]
    if not (latest / "chroma").exists():
        missing.append("chroma")
    return {
        "name": latest.name,
        "size_mb": round(size / 1024 / 1024, 1),
        "count": len(dirs),
        "missing": missing,
        "complete": not missing,
    }


def build() -> dict:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "containers": _section("containers", _containers),
        "db": _section("db", _db_digest),
        "backup": _section("backup", _latest_backup),
    }


def _print(d: dict) -> None:
    c = d.get("containers") or {}
    db = d.get("db") or {}
    b = d.get("backup") or {}
    done = db.get("tasks_completed_today", "?")
    failed = db.get("tasks_failed_today", "?")
    viol = db.get("violations_today", "?")
    last_at = db.get("last_reg_at") or "无记录"
    new_regs = db.get("regs_new_today", "?")
    pending = db.get("regs_pending", "?")
    print(f"=== 运转摘要 · {d['generated_at']} ===")
    print(f"容器      : {c.get('running', '?')}/{c.get('total', '?')} 运行中")
    print(f"今日任务  : 完成 {done} / 失败 {failed} · 检出 {viol} 条")
    print(f"心跳      : 最近法规入库 {last_at} · 今日新增 {new_regs} 条 · 待确认 {pending} 条")
    print(f"知识库    : 罚单 {db.get('penalties', '?')} 条 · 材料台账 {db.get('materials')}")
    if b:
        state = "完整" if b.get("complete") else f"⚠️ 缺件: {', '.join(b.get('missing') or [])}"
        print(f"备份      : 最近 {b['name']}（{b['size_mb']}MB · {state}）· 共 {b['count']} 份")
    else:
        print("备份      : 无")
    if db.get("zombie_pending"):
        print(f"⚠️ 堆积    : pending 任务 {db['zombie_pending']} 个（可能是停止的批次残留）")


def main() -> None:
    # 摘要要干净：抑制 SQLAlchemy 的 SQL echo（应用 logger 会给子 logger 配 handler，需一并关传播）
    for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False
    d = build()
    if "--json" in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    else:
        _print(d)


if __name__ == "__main__":
    main()
