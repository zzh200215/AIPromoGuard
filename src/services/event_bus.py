"""全局事件总线（P1 实时推送地基）——Redis pub/sub 跨进程扇出。

架构：事件产生于审查 worker 进程（celery）与 api 进程本身；SSE 端点在 api 进程
订阅并下发。跨进程用 Redis pub/sub（broker 复用同一 Redis，无需新组件）。

事件类型（payload.type）：
- task_status    任务状态变更（running/awaiting_review/completed/failed）
- task_stage     审查轨迹节点完成（stage_sink 增量落库同时发布）
- batch_progress 批量任务计数变化
- notification   站内通知（user_id 定向，SSE 连接层过滤）
- result_changed 判定确认/撤销（采纳统计脏标记，前端刷新）

可靠性约定（同 stage_sink 先例）：
- 发布失败静默（事件是增强，不阻断主流程；前端保留轮询兜底）；
- 单测环境（PYTEST_CURRENT_TEST）不碰真 Redis；
- payload 单条体积护栏（超长跳过）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

CHANNEL = "fcr:events"
_MAX_PAYLOAD_CHARS = 16_384

_client: Any = None  # 模块级缓存，避免每事件建连


def _get_client():
    global _client
    if _client is None:
        import redis

        from src.utils.config import settings

        _client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    return _client


def publish_event(event_type: str, data: dict | None = None, *, task_id: int | None = None,
                  batch_id: int | None = None, user_id: int | None = None) -> None:
    """向总线发布一条事件；任何失败静默（增强能力不阻断主流程）。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 单测防线：不碰真 Redis（发布/订阅格式正确性由专门单测覆盖）
    payload = json.dumps(
        {
            "type": event_type,
            "task_id": task_id,
            "batch_id": batch_id,
            "user_id": user_id,
            "data": data or {},
            "ts": int(time.time()),
        },
        ensure_ascii=False,
    )
    if len(payload) > _MAX_PAYLOAD_CHARS:
        logger.warning("事件 payload 超长（%s chars），跳过 type=%s", len(payload), event_type)
        return
    try:
        _get_client().publish(CHANNEL, payload)
    except Exception:
        logger.debug("事件发布失败 type=%s", event_type, exc_info=True)
