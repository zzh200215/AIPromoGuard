"""统一响应封装（PRD §12）。"""

import uuid
from typing import Any


def gen_trace_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


def ok(data: Any = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data, "trace_id": gen_trace_id()}


def fail(code: int, message: str, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data, "trace_id": gen_trace_id()}
