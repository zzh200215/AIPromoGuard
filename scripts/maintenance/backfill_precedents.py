"""回填历史人工判定到先例库（幂等，可重复执行）。

背景：先例沉淀挂在 confirm/revert API 端点上（sync_after_verdict），功能上线前
已存在的人工终态判定不会自动沉淀。本脚本按同一口径回填：

- 只处理 confirmed_by > 0 的结果（系统自动确认 confirmed_by 为空，设计上不沉淀，
  避免循环论证——见 sync_after_verdict docstring）；
- 逐条走 sync_after_verdict 统一路由：终态 upsert、pending（撤销复核）drop、
  其他状态跳过；upsert 幂等，重复执行无副作用；
- 向量侧与 DB 同步写入（embedding 为本地 BGE，不耗 LLM 配额）。

用法：uv run python scripts/maintenance/backfill_precedents.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func

from src.infrastructure.database.mysql import SessionLocal
from src.models import ReviewPrecedent, ReviewResult
from src.services.precedent_memory import sync_after_verdict


def main() -> int:
    db = SessionLocal()
    try:
        before = db.query(func.count(ReviewPrecedent.id)).scalar() or 0
        rows = (
            db.query(ReviewResult)
            .filter(
                ReviewResult.confirmed_by.isnot(None),
                ReviewResult.confirmed_by > 0,
            )
            .order_by(ReviewResult.id)
            .all()
        )
        print(f"候选人工判定 {len(rows)} 条（confirmed_by>0，任意状态）")
        for r in rows:
            sync_after_verdict(db, r)
        after = db.query(func.count(ReviewPrecedent.id)).scalar() or 0
        print(f"先例库 {before} → {after} 条（差值含翻案覆盖，非纯新增）")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
