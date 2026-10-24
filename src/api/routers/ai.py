"""AI Copilot 端点：任务审查问答与违规合规改写。

鉴权与普通业务接口一致（登录 + 任务访问权），LLM 未配置时服务层抛
LLM_CALL_FAILED / 503，前端据此提示「AI 服务未配置」，不做静默降级。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import ensure_task_access, require_permission
from src.api.schemas.ai import AskRequest, SummaryRequest
from src.infrastructure.database.mysql import get_db
from src.models import ReviewResult, ReviewTask, User
from src.services.review_copilot import (
    ask_review_question,
    load_copilot_history,
    rewrite_compliant,
    summarize_report,
    verdict_advice,
)
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/tasks/{task_id}/ask")
def ask_task_question(
    task_id: int,
    body: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """围绕任务审查报告的自由问答，回答附法规引用（可溯源）；多轮会话历史随任务落库。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok(ask_review_question(db, task, body.question.strip()))


@router.get("/tasks/{task_id}/ask-history")
def get_ask_history(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """任务问答历史（时间正序，refs 已反序列化）——Copilot 抽屉打开时恢复会话。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok({"messages": load_copilot_history(db, task_id)})


@router.post("/results/{result_id}/rewrite")
def rewrite_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """单条违规的合规改写：返回改写文案与逐条修改说明。"""
    result = db.get(ReviewResult, result_id)
    if result is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    task = db.get(ReviewTask, result.task_id)
    if task is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok(rewrite_compliant(db, result))


@router.post("/tasks/{task_id}/summary")
def summarize_task_report(
    task_id: int,
    body: SummaryRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """报告风险综述：随报告落盘进导出留档链路；结论变化后自动重算。

    body.force=true 供前端「重新生成」按钮强制刷新（忽略未过期缓存）。
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise AppError(ErrorCode.TASK_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok(summarize_report(db, task, force=bool(body and body.force)))


@router.post("/results/{result_id}/verdict-advice")
def result_verdict_advice(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_report")),
) -> dict:
    """判定辅助：AI 预判成立/误报与理由，仅供人工判定参考预填。"""
    result = db.get(ReviewResult, result_id)
    if result is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    task = db.get(ReviewTask, result.task_id)
    if task is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    ensure_task_access(db, task, current_user)
    return ok(verdict_advice(db, result))
