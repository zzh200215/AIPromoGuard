"""用户管理接口（W12 管理后台，PRD §3.2.9 用户权限 / §13.1 RBAC）。

仅管理员（manage_users 权限）可操作：创建 / 列表 / 启停 / 改角色 / 重置密码 / 删除。
禁止删除当前登录用户自身，避免管理员误操作导致系统失去管理入口。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.middleware.auth import require_permission
from src.infrastructure.database.mysql import get_db
from src.models import ReviewTask, User
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok
from src.utils.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

_ROLES = {"admin", "reviewer", "viewer"}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field("reviewer", pattern="^(admin|reviewer|viewer)$")
    department: str | None = Field(None, max_length=128)


class UserUpdate(BaseModel):
    role: str | None = Field(None, pattern="^(admin|reviewer|viewer)$")
    department: str | None = Field(None, max_length=128)
    status: int | None = Field(None, ge=0, le=1)


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "department": user.department,
        "status": user.status,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("")
def list_users(
    role: str | None = None,
    status: int | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if status is not None:
        query = query.filter(User.status == status)
    total = query.count()
    items = (
        query.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_user_out(u) for u in items],
        }
    )


@router.post("", status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    exists = db.query(User).filter(User.username == body.username).first()
    if exists:
        raise AppError(ErrorCode.PARAM_ERROR, "用户名已存在", http_status=409)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        department=body.department,
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(_user_out(user))


@router.get("/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.PARAM_ERROR, "用户不存在", http_status=404)
    return ok(_user_out(user))


@router.put("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.PARAM_ERROR, "用户不存在", http_status=404)
    # 禁止操作自身，防止把自己改掉/禁用后失去管理入口
    if user_id == current_user.id:
        raise AppError(ErrorCode.PARAM_ERROR, "不能修改当前登录用户", http_status=400)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return ok(_user_out(user))


@router.post("/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.PARAM_ERROR, "用户不存在", http_status=404)
    user.password_hash = hash_password(body.password)
    db.commit()
    return ok({"reset": user_id})


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
) -> dict:
    if user_id == current_user.id:
        raise AppError(ErrorCode.PARAM_ERROR, "不能删除当前登录用户", http_status=400)
    user = db.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.PARAM_ERROR, "用户不存在", http_status=404)
    # 无外键约束，应用层防孤儿数据：名下有审查任务的用户只能禁用不能删
    task_count = db.query(ReviewTask).filter(ReviewTask.created_by == user_id).count()
    if task_count:
        raise AppError(
            ErrorCode.PARAM_ERROR,
            f"该用户名下有 {task_count} 个审查任务，不能删除；可将账号禁用（status=0）",
            http_status=409,
        )
    db.delete(user)
    db.commit()
    return ok({"deleted": user_id})
