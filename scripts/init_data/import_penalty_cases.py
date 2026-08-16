"""导入处罚案例（penalty_cases 表，W9 周三）。

数据来源: scripts/crawl/fetch_penalty_cases.py 抓取的监管机构官方公开处罚
（金监总局各监管局行政处罚信息公开表 + 证监会行政处罚决定书，见同目录
penalty_cases.json，每条含 source_url 可溯源）；早期 AI 生成样例已被替换。

幂等: 按 case_name upsert；related_regulations 存储为关联法规的 id 数组
（由法规名称解析得到，未匹配到的名称跳过并打印告警）。
--replace: 先清空表再导入（数据源整体切换时用，如从 AI 样例换真实数据）。

用法:
    python scripts/init_data/import_penalty_cases.py [--json 文件路径] [--replace]
默认读取 scripts/init_data/penalty_cases.json。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.models import PenaltyCase, Regulation

DEFAULT_JSON = Path(__file__).resolve().parent / "penalty_cases.json"

# PenaltyCase 模型列白名单：JSON 里的 source_url / source 等溯源字段不入库
_COLUMNS = ("case_name", "penalty_org", "penalty_date", "penalty_result", "violation_summary")


def main() -> None:
    json_path = (
        Path(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else DEFAULT_JSON
    )
    with json_path.open(encoding="utf-8") as f:
        items = json.load(f)

    db = SessionLocal()
    try:
        if "--replace" in sys.argv:
            deleted = db.query(PenaltyCase).delete()
            print(f"  - --replace: 清空既有案例 {deleted} 条")
            db.commit()
        # 法规名 → id（不含书名号）
        reg_id_by_name = {
            r.regulation_name: r.id
            for r in db.query(Regulation.id, Regulation.regulation_name).all()
        }
        added = updated = skipped_regs = 0
        for item in items:
            case = db.query(PenaltyCase).filter(PenaltyCase.case_name == item["case_name"]).first()
            # 解析法规名 → id
            reg_ids = []
            for name in item.get("related_regulations", []):
                if name in reg_id_by_name:
                    reg_ids.append(reg_id_by_name[name])
                else:
                    skipped_regs += 1
                    print(f"  ! 未匹配法规: {name}（案例: {item['case_name']}）")
            fields = {k: item[k] for k in _COLUMNS if k in item}
            fields["related_regulations"] = reg_ids
            if case is None:
                db.add(PenaltyCase(**fields))
                added += 1
                print(f"  + 案例: {item['case_name']}")
            else:
                changed = any(getattr(case, k) != v for k, v in fields.items())
                if changed:
                    for k, v in fields.items():
                        setattr(case, k, v)
                    updated += 1
                    print(f"  ~ 更新案例: {item['case_name']}")
        db.commit()
        print(f"完成: 共 {len(items)} 条, 新增 {added}, 更新 {updated}, 未匹配法规 {skipped_regs}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
