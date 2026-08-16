"""知识图谱查询接口（PRD §5.5）。

提供违规点关联查询（法规/违规模式/处罚案例）与图谱统计。
Neo4j 不可用时返回空结果（优雅降级），不阻塞主流程。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_current_user
from src.models import User
from src.services import graph_service
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/graph", tags=["graph"])

# W19：领域白名单由 app.yaml domains 驱动，新增领域无需改代码
_FALLBACK_DOMAINS = {"banking", "fund", "insurance"}


def _valid_domains() -> set[str]:
    cfg = settings.app_config("domains") or {}
    return set(cfg.keys()) if cfg else _FALLBACK_DOMAINS


def _check_domain(domain: str | None) -> None:
    if domain and domain not in _valid_domains():
        raise AppError(ErrorCode.PARAM_ERROR, f"领域需为 {sorted(_valid_domains())} 之一")


class GraphQuery(BaseModel):
    query: str = Field(..., min_length=2, description="违规点描述，如'承诺保本保收益'")
    domain: str | None = Field(None, description="领域过滤 banking/fund/insurance")
    top_k: int = Field(10, ge=1, le=50)


class CaseQuery(BaseModel):
    text: str = Field(..., min_length=2, description="违规内容，用于相似案例推荐")
    domain: str | None = None
    top_k: int = Field(5, ge=1, le=20)


@router.post("/query")
def graph_query(
    body: GraphQuery,
    current_user: User = Depends(get_current_user),
) -> dict:
    """违规点 → 关联违规模式 / 法规条款 / 历史处罚案例。"""
    _check_domain(body.domain)
    try:
        data = graph_service.query_graph(body.query, body.domain, body.top_k)
    except Exception as exc:
        raise AppError(ErrorCode.GRAPH_QUERY_FAILED, str(exc)) from exc
    return ok(data)


@router.post("/cases/recommend")
def recommend_cases(
    body: CaseQuery,
    current_user: User = Depends(get_current_user),
) -> dict:
    """基于违规内容相似度推荐历史处罚案例。"""
    _check_domain(body.domain)
    try:
        cases = graph_service.similar_cases(body.text, body.domain, body.top_k)
    except Exception as exc:
        raise AppError(ErrorCode.GRAPH_QUERY_FAILED, str(exc)) from exc
    return ok({"total": len(cases), "cases": cases})


@router.get("/stats")
def graph_stats(
    current_user: User = Depends(get_current_user),
) -> dict:
    """图谱节点与关系计数（验证 / 监控用）。"""
    return ok(graph_service.graph_stats())
