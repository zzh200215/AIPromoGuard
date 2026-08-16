from fastapi import APIRouter, Response
from sqlalchemy import text

from src.infrastructure.database.mysql import SessionLocal
from src.utils.config import settings
from src.utils.response import ok

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(response: Response) -> dict:
    app_cfg = settings.app_config("app")
    dependencies: dict[str, bool] = {}
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            dependencies["mysql"] = True
        finally:
            db.close()
    except Exception:
        dependencies["mysql"] = False

    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
        dependencies["redis"] = True
    except Exception:
        dependencies["redis"] = False

    healthy = all(dependencies.values())
    if not healthy:
        response.status_code = 503
    return ok(
        {
            "status": "ok" if healthy else "degraded",
            "service": app_cfg.get("name", "financial-compliance-review"),
            "version": app_cfg.get("version", "0.1.0"),
            "env": settings.app_env,
            "dependencies": dependencies,
        }
    )
