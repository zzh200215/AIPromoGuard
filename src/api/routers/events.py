"""SSE 实时事件流（P1）——GET /api/v1/events。

认证：EventSource 无法携带 Authorization 头，接受 `?token=` 查询参数（与登录
同源的 JWT）；也兼容常规 Bearer 头。token 过期时连接以 401 关闭，前端据此
重新取 token 重连。

下发：订阅 Redis 频道 fcr:events，转发为 SSE 默认 message 事件（data 为 JSON）。
- user_id 定向事件（如站内通知）只发给对应用户，其余广播给所有已连接用户；
- 15s 心跳注释行保活（防代理/浏览器空闲断连）；
- Redis 不可达时降级为纯心跳流（连接保持、无事件——前端轮询兜底照常工作）。
"""

from __future__ import annotations

import asyncio
import json

import redis.asyncio as aredis
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from src.infrastructure.database.mysql import SessionLocal
from src.models import User
from src.services.event_bus import CHANNEL
from src.utils.config import settings
from src.utils.logger import get_logger
from src.utils.security import decode_token

logger = get_logger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

_HEARTBEAT_SECONDS = 15


def _resolve_user(request: Request, token: str | None) -> User | None:
    raw = token or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not raw:
        return None
    try:
        payload = decode_token(raw)
    except Exception:
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    db = SessionLocal()
    try:
        return db.get(User, int(sub))
    finally:
        db.close()


@router.get("")
async def event_stream(request: Request, token: str | None = Query(default=None)):
    user = _resolve_user(request, token)
    if user is None:
        return StreamingResponse(
            iter(["event: error\ndata: {\"type\":\"auth_failed\"}\n\n"]),
            status_code=401,
            media_type="text/event-stream",
        )
    user_id = user.id

    async def stream():
        hello = json.dumps({"type": "hello", "data": {"user_id": user_id}}, ensure_ascii=False)
        yield "retry: 3000\n\n"
        yield f"data: {hello}\n\n"
        pubsub = None
        try:
            client = aredis.from_url(settings.redis_url, socket_connect_timeout=2)
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
        except Exception:
            logger.warning("SSE 订阅 Redis 失败，降级为纯心跳流", exc_info=True)

        try:
            while True:
                if await request.is_disconnected():
                    break
                message = None
                if pubsub is not None:
                    try:
                        message = await asyncio.wait_for(
                            pubsub.get_message(ignore_subscribe_messages=True),
                            timeout=_HEARTBEAT_SECONDS,
                        )
                    except TimeoutError:
                        message = None
                    except Exception:
                        logger.warning("SSE 读取事件失败，关闭该连接", exc_info=True)
                        break
                if message and message.get("type") == "message":
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, ValueError):
                        continue
                    if payload.get("user_id") and payload["user_id"] != user_id:
                        continue  # 用户定向事件不跨用户下发
                    yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
                else:
                    yield ": heartbeat\n\n"  # 注释行保活
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
