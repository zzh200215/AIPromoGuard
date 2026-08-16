"""FastAPI 应用入口。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.middleware.audit import AuditMiddleware
from src.api.routers import (
    auth,
    batches,
    documents,
    graph,
    health,
    monitor,
    regulations,
    reports,
    results,
    rules,
    tasks,
    trends,
    users,
)
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger
from src.utils.response import fail

logger = get_logger(__name__)


def create_app() -> FastAPI:
    if settings.app_env == "prod" and (
        not settings.jwt_secret or settings.jwt_secret.startswith("change-me")
    ):
        raise RuntimeError("JWT_SECRET must be configured with a non-default value in production")
    app = FastAPI(
        title="金融产品合规智能审查系统",
        description="基于 Agentic RAG + 规则引擎的智能合规审查服务",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/api/v1/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env != "prod" else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 最后注册的中间件最先执行；审计需包裹全部请求
    app.add_middleware(AuditMiddleware)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(batches.router, prefix="/api/v1")
    app.include_router(regulations.router, prefix="/api/v1")
    app.include_router(rules.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    app.include_router(results.router, prefix="/api/v1")
    app.include_router(graph.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(monitor.router, prefix="/api/v1")
    app.include_router(trends.router, prefix="/api/v1")

    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=fail(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("参数校验失败: %s", exc.errors())
        return JSONResponse(
            status_code=400,
            content=fail(ErrorCode.PARAM_ERROR, "参数错误", {"detail": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content=fail(ErrorCode.INTERNAL_ERROR, "系统内部错误"),
        )


app = create_app()
