"""合规洞察接口：一屏聚合审查运行数据（只读）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user
from src.infrastructure.database.mysql import get_db
from src.models import User
from src.services import insights_service
from src.utils.response import ok

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """卡片 + 风险/来源分布 + 规则与法规命中 Top + 30 天趋势 + 复核漏斗 + 整改闭环。"""
    return ok(insights_service.overview(db))
