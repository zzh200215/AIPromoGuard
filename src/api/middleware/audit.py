"""审计日志中间件：记录业务 API 的用户操作（PRD §13.3）。

异步请求内同步写库会阻塞事件循环，改用后台线程异步落库；
仅记录 /api/v1 业务接口，跳过 health / openapi / docs。
"""

from concurrent.futures import ThreadPoolExecutor

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.utils.logger import get_logger
from src.utils.security import decode_token

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)

_SKIP_PREFIXES = ("/api/v1/health", "/api/v1/openapi.json", "/docs", "/redoc")


def _parse_user(request: Request) -> tuple[int | None, str | None]:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, None
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        return int(payload.get("sub", "0")), payload.get("username") or payload.get("role")
    except Exception:
        return None, None


def _resource_from_path(path: str) -> tuple[str | None, str | None]:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3:  # /api/v1/<资源>/<id>...
        return parts[2], (parts[3] if len(parts) > 3 else None)
    if len(parts) == 2:  # /api/v1/<资源>
        return parts[1], None
    return None, None


def _write_audit(**kwargs) -> None:
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import AuditLog

        db = SessionLocal()
        try:
            db.add(AuditLog(**{k: v for k, v in kwargs.items() if v is not None}))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("审计日志写入失败: %s", exc)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/v1") and not path.startswith(_SKIP_PREFIXES):
            user_id, username = _parse_user(request)
            resource_type, resource_id = _resource_from_path(path)
            _executor.submit(
                _write_audit,
                user_id=user_id,
                username=username,
                action=f"{request.method} {path}"[:128],
                resource_type=resource_type,
                resource_id=resource_id,
                client_ip=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "")[:255],
                status_code=response.status_code,
            )
        return response
