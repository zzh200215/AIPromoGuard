"""密码哈希与 JWT 令牌。"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, username: str | None = None) -> str:
    if not settings.jwt_secret or settings.jwt_secret.startswith("change-me"):
        raise RuntimeError("JWT_SECRET must be configured with a non-default value")
    payload = {
        "sub": str(user_id),
        "role": role,
        "username": username,
        "exp": datetime.now(UTC)
        + timedelta(minutes=settings.jwt_access_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    if not settings.jwt_secret or settings.jwt_secret.startswith("change-me"):
        raise AppError(ErrorCode.INTERNAL_ERROR, "JWT_SECRET 未配置", http_status=500)
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AppError(
            ErrorCode.UNAUTHORIZED, "无效或已过期的登录凭证", http_status=401
        ) from exc
