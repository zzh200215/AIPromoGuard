"""结论生命周期时间线（F2-3）：把一条审查结论的判定轨迹组装成时间线事件。

数据来源（全是既有数据，零新表）：
- ReviewResult 本身：检出时刻、来源、置信度、系统自动确认与否
- AuditLog（resource_type=review_result）：人工判定（含批量）、翻案、撤销复核

设计为纯函数（build_trail），路由层只做查询与序列化——
对齐项目"纯函数判定 + DB 编排分离"的测试惯例。
"""

from __future__ import annotations

import json
from typing import Any

# 事件类型（前端渲染用）：检出 / 系统自动确认 / 人工判定 / 翻案 / 撤销复核
EVENT_DETECTED = "detected"
EVENT_AUTO_CONFIRMED = "auto_confirmed"
EVENT_CONFIRM = "confirm"
EVENT_OVERTURN = "overturn"
EVENT_REVERT = "revert"

_STATUS_LABELS = {
    "pending_confirm": "待复核",
    "confirmed": "已确认违规",
    "false_positive": "已剔除误报",
}

# 已判定状态：翻案 = 从已判定状态改成另一个判定（改判既有结论）。
# 注意 before_status（状态：pending_confirm/confirmed/false_positive）与
# verdict（判定：confirmed/false_positive）不同命名空间，直接比较会把
# 常规复核（pending → confirmed）误判为翻案。
_JUDGED_STATUSES = {"confirmed", "false_positive"}

_SOURCE_LABELS = {
    "rule": "规则引擎",
    "llm": "LLM 语义判定",
    "hybrid": "双引擎交叉",
    "vlm": "视觉模型",
}


def _parse_detail(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def build_trail(result, ops: list) -> list[dict]:
    """组装时间线事件（按时间顺序）。

    result: ReviewResult 实例（需 id/status/confidence_score/violation_type/
            created_at/confirmed_by）
    ops:    AuditLog 列表（该结论的审计留痕，按 id 升序）
    """
    events: list[dict] = []

    # 1) 检出：结论诞生（来源 + 置信度），系统自动确认在此刻一并说明
    source = _SOURCE_LABELS.get(getattr(result, "violation_type", ""), "系统")
    confidence = getattr(result, "confidence_score", None)
    conf_text = f"，置信度 {float(confidence):.2f}" if confidence is not None else ""
    auto = getattr(result, "confirmed_by", None) == 0
    events.append(
        {
            "at": result.created_at.isoformat(timespec="seconds") if result.created_at else "",
            "type": EVENT_AUTO_CONFIRMED if auto else EVENT_DETECTED,
            "actor": "系统",
            "detail": (
                f"{source}检出（{_STATUS_LABELS.get(result.status, result.status)}{conf_text}）"
                if not auto
                else f"{source}检出后按分流规则自动确认（{conf_text.lstrip('，')}）"
            ),
        }
    )

    # 2) 人工操作留痕：判定 / 翻案 / 撤销
    for op in ops:
        detail = _parse_detail(getattr(op, "detail", None))
        before = detail.get("before_status")
        verdict = detail.get("verdict")
        bulk = bool(detail.get("bulk"))
        actor = getattr(op, "username", None) or "系统"
        if getattr(op, "action", "") == "result.revert":
            text = f"撤销复核，恢复为{_STATUS_LABELS.get(before or '', before or '待复核')}"
            etype = EVENT_REVERT
        else:
            flipped = (
                before in _JUDGED_STATUSES and verdict is not None and before != verdict
            )
            verb = "翻案改判" if flipped else "判定"
            text = (
                f"{verb}为{_STATUS_LABELS.get(verdict or '', verdict or '')}"
                f"（原：{_STATUS_LABELS.get(before or '', before or '—')}）"
            )
            etype = EVENT_OVERTURN if flipped else EVENT_CONFIRM
        if detail.get("before_auto_confirmed"):
            text += "｜纠错对象为系统自动确认"
        if bulk:
            text += "｜批量操作"
        events.append(
            {
                "at": op.created_at.isoformat(timespec="seconds") if op.created_at else "",
                "type": etype,
                "actor": actor,
                "detail": text,
            }
        )
    return events
