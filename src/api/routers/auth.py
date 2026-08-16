from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user
from src.api.schemas.auth import LoginRequest
from src.infrastructure.database.mysql import get_db
from src.models import User
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok
from src.utils.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", http_status=401)
    if user.status != 1:
        raise AppError(ErrorCode.FORBIDDEN, "账号已禁用", http_status=403)
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
