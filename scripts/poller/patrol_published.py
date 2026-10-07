"""发布后内容巡检入口（R3-1）：与 poll_regulators.py 同构的定时任务 CLI.

轮询台账登记的已发布渠道（publish_url，已授权自有渠道），与批准版内容
指纹做双层判定（containment + 关键数字缺失，见 services/content_patrol），
changed 自动创建复审任务。定时方式与 poll_regulators 一致：外部计划任务
（Windows 计划任务 / cron）按巡检周期调用本脚本，默认建议 7 天。

用法:
    python scripts/poller/patrol_published.py                     # 全量在用材料
    python scripts/poller/patrol_published.py --material-ids 1,2  # 指定材料
    python scripts/poller/patrol_published.py --dry-run           # 只打印计划，不抓取不落库
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.infrastructure.database.mysql import SessionLocal
from src.models import ProductMaterial
from src.services.content_patrol import patrol_materials


def main() -> int:
    parser = argparse.ArgumentParser(description="发布后内容巡检")
    parser.add_argument(
        "--material-ids",
        default="",
        help="逗号分隔的材料 id（缺省=全部登记了 publish_url 的在用材料）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印巡检计划（材料清单），不抓取不落库"
    )
    args = parser.parse_args()

    ids = [int(x) for x in args.material_ids.split(",") if x.strip()]
    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — 计划任务场景需明确可读的失败信息
        print(f"MySQL 不可用，巡检中止（启动 docker compose 后重试）：{exc}")
        return 2
    try:
        if args.dry_run:
            query = db.query(ProductMaterial).filter(
                ProductMaterial.publish_url.isnot(None),
                ProductMaterial.status == "active",
            )
            if ids:
                query = query.filter(ProductMaterial.id.in_(ids))
            plan = [
                {"material_id": m.id, "name": m.name, "url": m.publish_url, "channel": m.channel}
                for m in query.all()
            ]
            print(f"巡检计划（dry-run，共 {len(plan)} 项，不抓取不落库）：")
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        result = patrol_materials(db, ids)
    finally:
        db.close()

    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "outcomes"},
            ensure_ascii=False,
            indent=2,
        )
    )
    # changed/gone 属需人工跟进的信号：有则退出码 1（计划任务可据此告警）
    attention = result["counts"].get("changed", 0) + result["counts"].get("gone", 0)
    return 1 if attention else 0


if __name__ == "__main__":
    sys.exit(main())
