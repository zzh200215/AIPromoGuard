"""JWT 认证与 RBAC 权限依赖（角色权限对齐 roles 表种子数据，PRD §13.1）。"""


from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.infrastructure.database.mysql import get_db
from src.models import ReviewBatch, ReviewTask, Role, User
from src.utils.errors import AppError, ErrorCode
from src.utils.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppError(ErrorCode.UNAUTHORIZED, http_status=401)
    payload = decode_token(credentials.credentials)
    user_id = int(payload.get("sub", "0"))
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        raise AppError(ErrorCode.UNAUTHORIZED, http_status=401)
    return user


def _role_permissions(db: Session, role_name: str) -> set[str]:
    role = db.query(Role).filter(Role.name == role_name).first()
    return set(role.permissions or []) if role else set()


def require_permission(permission: str):
    """返回一个 FastAPI 依赖：校验当前用户角色是否包含指定权限。"""

    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        perms = _role_permissions(db, current_user.role)
        if permission not in perms:
            raise AppError(ErrorCode.FORBIDDEN, http_status=403)
        return current_user

    return checker


def ensure_task_access(db: Session, task: object, current_user: User) -> None:
    """Enforce tenant and department isolation for task-derived resources."""
    if current_user.role == "admin" or getattr(task, "created_by", None) == current_user.id:
        return
    owner_id = getattr(task, "created_by", None)
    if owner_id and current_user.department:
        owner = db.get(User, owner_id)
        if owner and owner.department == current_user.department:
            return
    raise AppError(ErrorCode.FORBIDDEN, http_status=403)


def ensure_batch_access(db: Session, batch: object, current_user: User) -> None:
    """Enforce tenant and department isolation for batch-derived resources."""
    if current_user.role == "admin" or getattr(batch, "created_by", None) == current_user.id:
        return
    owner_id = getattr(batch, "created_by", None)
    if owner_id and current_user.department:
        owner = db.get(User, owner_id)
        if owner and owner.department == current_user.department:
            return
    raise AppError(ErrorCode.FORBIDDEN, http_status=403)


def task_access_filter(current_user: User):
    """Return the SQL predicate for a task owner or a colleague in the same department."""
    if current_user.department:
        return or_(
            ReviewTask.created_by == current_user.id,
            User.department == current_user.department,
        )
    return ReviewTask.created_by == current_user.id


def batch_access_filter(current_user: User):
    """Return the SQL predicate for a batch owner or a colleague in the same department."""
    if current_user.department:
        return or_(
            ReviewBatch.created_by == current_user.id,
            User.department == current_user.department,
        )
    return ReviewBatch.created_by == current_user.id
