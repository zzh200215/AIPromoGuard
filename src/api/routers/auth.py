"""认证接口：登录（带失败限速）与当前用户信息。"""

import time
from threading import Lock

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user
from src.api.schemas.auth import LoginRequest
from src.infrastructure.database.mysql import get_db
from src.models import User
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger
from src.utils.response import ok
from src.utils.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

logger = get_logger(__name__)

# 登录失败限速：同一用户名 15 分钟窗口内连续失败 5 次即锁定至窗口结束。
# 进程内存实现（重启清零、单 worker 有效）；多 worker/多实例部署时应迁移到 Redis。
_MAX_FAILURES = 5
_LOCK_WINDOW = 15 * 60
_failed_attempts: dict[str, list[float]] = {}
_failed_lock = Lock()


def _recent_failures(username: str, now: float) -> list[float]:
    """返回窗口内失败时间戳并顺手清理过期项。"""
    with _failed_lock:
        attempts = [t for t in _failed_attempts.get(username, []) if now - t < _LOCK_WINDOW]
        if attempts:
            _failed_attempts[username] = attempts
        else:
            _failed_attempts.pop(username, None)
        return attempts


def _record_failure(username: str, now: float) -> None:
    with _failed_lock:
        _failed_attempts.setdefault(username, []).append(now)


def _clear_failures(username: str) -> None:
    with _failed_lock:
        _failed_attempts.pop(username, None)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    now = time.monotonic()
    failures = _recent_failures(body.username, now)
    if len(failures) >= _MAX_FAILURES:
        logger.warning("登录锁定触发: username=%s 连续失败 %s 次", body.username, len(failures))
        raise AppError(
            ErrorCode.FORBIDDEN, "失败次数过多，账号已临时锁定，请15分钟后重试", http_status=429
        )

    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        _record_failure(body.username, now)
        # 登录请求无 token，审计中间件记不到用户，此处补留痕（只记用户名，绝不记密码）
        logger.warning(
            "登录失败: username=%s 剩余尝试 %s 次", body.username, _MAX_FAILURES - len(failures) - 1
        )
        raise AppError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", http_status=401)
    if user.status != 1:
        raise AppError(ErrorCode.FORBIDDEN, "账号已禁用", http_status=403)
    _clear_failures(body.username)
    return ok(
        {
            "access_token": create_access_token(user.id, user.role, user.username),
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
            },
        }
    )


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    return ok(
        {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role,
            "department": current_user.department,
        }
    )
