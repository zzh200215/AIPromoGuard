"""stage_log 节点级增量落库——审查轨迹"实时化"（2026-10-15）。

背景：stage_log 原本只在图跑完（review_service._finalize_task）或人工复核
暂停时整体写入 review_tasks.stages，运行中前端轨迹面板只有步骤骨架
（2026-10-15 完成度审计发现的过度声明，本模块即其修复）。

机制：graph._wrap 在每个节点成功完成时回调本模块，把该节点的 stage 条目
原子合并进 review_tasks.stages——MySQL JSON_MERGE_PATCH 单语句合并，
无读改写竞态，天然兼容 rule_scan ∥ llm_scan 并行分支（各自完成时刻
只补各自的键）。前端轮询任务详情即可看到"逐节点点亮"。

可靠性约定：
- 失败静默降级（debug 日志）：增量落库绝不阻断审查主流程；
  最终一致性由 _finalize_task 完成时的整体覆盖兜底；
- 单测环境（存在 PYTEST_CURRENT_TEST）不写真库——沿用 2026-10-13
  "本地全量测试污染真库"的教训，把侧信道写入挡在单测之外；
- 体积护栏：单条 entry 超限即跳过（正常条目为计数 + top-3 名称，
  远小于上限；超长说明上游异常，跳过比写坏数据安全）。
"""

from __future__ import annotations

import json
import os

from src.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_ENTRY_CHARS = 16_384


def persist_stage(task_id: int | None, name: str, entry: dict) -> None:
    """把单个节点的 stage 条目原子合并进 review_tasks.stages；任何失败不外抛。"""
    if not task_id or not name or not isinstance(entry, dict):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 单测防线：不写真库（增量落库的正确性由线上实跑验证）
    payload = json.dumps({name: entry}, ensure_ascii=False)
    if len(payload) > _MAX_ENTRY_CHARS:
        logger.warning("stage 条目超长（%s chars），跳过增量落库 node=%s", len(payload), name)
        return
    try:
        from sqlalchemy import text

        from src.infrastructure.database.mysql import engine

        stmt = text(
            """
            UPDATE review_tasks
            SET stages = JSON_MERGE_PATCH(COALESCE(stages, JSON_OBJECT()), :entry)
            WHERE id = :task_id
            """
        )
        with engine.begin() as conn:
            conn.execute(stmt, {"entry": payload, "task_id": task_id})
        # SSE 实时推送（P1）：节点轨迹落库即广播；失败静默同落库纪律
        try:
            from src.services.event_bus import publish_event

            publish_event("task_stage", {"node": name, "detail": entry}, task_id=task_id)
        except Exception:
            logger.debug("stage 事件发布跳过 task=%s node=%s", task_id, name)
    except Exception:
        # 静默降级：失败不影响审查；完成时 _finalize_task 整体覆盖兜底
        logger.debug("stage 增量落库跳过 task=%s node=%s", task_id, name, exc_info=True)
