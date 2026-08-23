"""LangGraph checkpoint 的 MySQL 持久化实现。

langgraph-checkpoint 官方只提供 Sqlite/Postgres saver，本项目主库是 MySQL，
这里按 BaseCheckpointSaver 4.x 接口实现 MySQLCheckpointSaver：

- checkpoint 与 metadata 用 JsonPlusSerializer.dumps_typed 序列化为 LONGBLOB，
  与官方 saver 一致（metadata 里可能出现异常对象等非 JSON 值，不能走 JSON 列）；
- put_writes 用 REPLACE INTO 幂等写入（同 task 重写覆盖）；
- setup() 幂等建表，运行期懒调用，无需独立迁移步骤。

解决的生产问题：InMemorySaver 仅进程内有效——API/worker 重启后 awaiting_review
任务的 checkpoint 丢失，无法续跑；Celery 与 API 分进程部署时同样失效。
"""

import logging
from collections.abc import Iterator
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    RunnableConfig,
)
from sqlalchemy import text

from src.infrastructure.database.mysql import engine

logger = logging.getLogger(__name__)

_CREATE_CHECKPOINTS = """
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    thread_id           VARCHAR(128)  NOT NULL,
    checkpoint_ns       VARCHAR(255)  NOT NULL DEFAULT '',
    checkpoint_id       VARCHAR(64)   NOT NULL,
    parent_checkpoint_id VARCHAR(64)  DEFAULT NULL,
    type                VARCHAR(64)   NOT NULL,
    checkpoint          LONGBLOB      NOT NULL,
    metadata_type       VARCHAR(64)   DEFAULT NULL,
    metadata            LONGBLOB      DEFAULT NULL,
    UNIQUE KEY uk_cp_thread (thread_id, checkpoint_ns, checkpoint_id),
    KEY idx_cp_thread (thread_id, checkpoint_ns, id),
    KEY idx_cp_parent (parent_checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='LangGraph checkpoint 持久化(人工复核中断/恢复)'
"""

_CREATE_WRITES = """
CREATE TABLE IF NOT EXISTS langgraph_writes (
    thread_id     VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(64)  NOT NULL,
    task_id       VARCHAR(64)  NOT NULL,
    idx           INT          NOT NULL,
    channel       VARCHAR(255) NOT NULL,
    type          VARCHAR(64)  NOT NULL,
    write_blob     LONGBLOB     NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='LangGraph pending writes(节点写通道)'
"""


def _configurable(config: RunnableConfig) -> tuple[str, str, str | None]:
    """从 RunnableConfig 提取 (thread_id, checkpoint_ns, checkpoint_id)。"""
    conf = config["configurable"] if config else {}
    thread_id = conf.get("thread_id")
    if not thread_id:
        raise ValueError("configurable.thread_id 缺失，无法定位 checkpoint")
    return thread_id, conf.get("checkpoint_ns", ""), conf.get("checkpoint_id")


class MySQLCheckpointSaver(BaseCheckpointSaver):
    """MySQL 版 LangGraph checkpointer（同步接口，线程池执行模型下使用）。"""

    def setup(self) -> None:
        """幂等建表；已有库升级时无需手工迁移。"""
        with engine.begin() as conn:
            conn.execute(text(_CREATE_CHECKPOINTS))
            conn.execute(text(_CREATE_WRITES))

    # ---------- 写入 ----------

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        thread_id, ns, _ = _configurable(config)
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(metadata)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "REPLACE INTO langgraph_checkpoints"
                    " (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,"
                    "  type, checkpoint, metadata_type, metadata)"
                    " VALUES (:thread_id, :ns, :cid, :parent, :cp_type, :cp_blob,"
                    "  :md_type, :md_blob)"
                ),
                {
                    "thread_id": thread_id,
                    "ns": ns,
                    "cid": checkpoint["id"],
                    "parent": config.get("configurable", {}).get("checkpoint_id")
                    if config
                    else None,
                    "cp_type": cp_type,
                    "cp_blob": cp_blob,
                    "md_type": md_type,
                    "md_blob": md_blob,
                },
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns, checkpoint_id = _configurable(config)
        if not checkpoint_id:
            raise ValueError("put_writes 需要 configurable.checkpoint_id")
        params: list[dict[str, Any]] = []
        for idx, (channel, value) in enumerate(writes):
            type_, blob = self.serde.dumps_typed(value)
            params.append(
                {
                    "thread_id": thread_id,
                    "ns": ns,
                    "cid": checkpoint_id,
                    "task_id": task_id,
                    "idx": idx,
                    "channel": channel,
                    "type": type_,
                    "write_blob": blob,
                }
            )
        if not params:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "REPLACE INTO langgraph_writes"
                    " (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,"
                    "  channel, type, write_blob)"
                    " VALUES (:thread_id, :ns, :cid, :task_id, :idx, :channel,"
                    "  :type, :write_blob)"
                ),
                params,
            )

    # ---------- 读取 ----------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, ns, checkpoint_id = _configurable(config)
        query = (
            "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint,"
            " metadata_type, metadata"
            " FROM langgraph_checkpoints"
            " WHERE thread_id = :thread_id AND checkpoint_ns = :ns"
        )
        params: dict[str, Any] = {"thread_id": thread_id, "ns": ns}
        if checkpoint_id:
            query += " AND checkpoint_id = :cid"
            params["cid"] = checkpoint_id
        else:
            query += " ORDER BY id DESC"
        query += " LIMIT 1"
        with engine.begin() as conn:
            row = conn.execute(text(query), params).mappings().first()
            if row is None:
                return None
            writes_rows = conn.execute(
                text(
                    "SELECT task_id, channel, type, write_blob FROM langgraph_writes"
                    " WHERE thread_id = :thread_id AND checkpoint_ns = :ns"
                    " AND checkpoint_id = :cid ORDER BY task_id, idx"
                ),
                {"thread_id": thread_id, "ns": ns, "cid": row["checkpoint_id"]},
            ).mappings().all()

        pending_writes: list[PendingWrite] = [
            (
                w["task_id"],
                w["channel"],
                self.serde.loads_typed((w["type"], bytes(w["write_blob"]))),
            )
            for w in writes_rows
        ]
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": row["checkpoint_id"],
                }
            },
            checkpoint=self.serde.loads_typed(
                (row["type"], bytes(row["checkpoint"]))
            ),
            metadata=self.serde.loads_typed(
                (row["metadata_type"], bytes(row["metadata"]))
            )
            if row["metadata"] is not None
            else {},
            parent_config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": row["parent_checkpoint_id"],
                }
            }
            if row["parent_checkpoint_id"]
            else None,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if filter:
            for key, value in filter.items():
                if not isinstance(value, str | int | float | bool):
                    raise ValueError(
                        f"checkpoint filter 仅支持标量相等: {key}={value!r}"
                    )
        query = (
            "SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,"
            " type, checkpoint, metadata_type, metadata FROM langgraph_checkpoints"
        )
        params: dict[str, Any] = {}
        conditions: list[str] = []
        if config:
            thread_id, ns, checkpoint_id = _configurable(config)
            conditions.append("thread_id = :thread_id")
            params["thread_id"] = thread_id
            if ns:
                conditions.append("checkpoint_ns = :ns")
                params["ns"] = ns
            if checkpoint_id:
                conditions.append("checkpoint_id = :cid")
                params["cid"] = checkpoint_id
        if before and before.get("configurable", {}).get("checkpoint_id"):
            conditions.append("checkpoint_id < :before_cid")
            params["before_cid"] = before["configurable"]["checkpoint_id"]
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"
        if limit:
            query += " LIMIT :n"
            params["n"] = limit
        with engine.begin() as conn:
            rows = conn.execute(text(query), params).mappings().all()
        for row in rows:
            metadata = (
                self.serde.loads_typed((row["metadata_type"], bytes(row["metadata"])))
                if row["metadata"] is not None
                else {}
            )
            if filter and any(metadata.get(k) != v for k, v in filter.items()):
                continue
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": row["thread_id"],
                        "checkpoint_ns": row["checkpoint_ns"],
                        "checkpoint_id": row["checkpoint_id"],
                    }
                },
                checkpoint=self.serde.loads_typed(
                    (row["type"], bytes(row["checkpoint"]))
                ),
                metadata=metadata,
                parent_config={
                    "configurable": {
                        "thread_id": row["thread_id"],
                        "checkpoint_ns": row["checkpoint_ns"],
                        "checkpoint_id": row["parent_checkpoint_id"],
                    }
                }
                if row["parent_checkpoint_id"]
                else None,
            )

    def get_next_version(self, current: int | None, channel: str | None) -> int:
        return (current or 0) + 1

    # ---------- 清理 ----------

    def delete_thread(self, thread_id: str) -> int:
        """删除一个线程的全部 checkpoint 与 writes（任务终态后的卫生清理）。"""
        with engine.begin() as conn:
            writes = conn.execute(
                text("DELETE FROM langgraph_writes WHERE thread_id = :t"),
                {"t": thread_id},
            ).rowcount
            cps = conn.execute(
                text("DELETE FROM langgraph_checkpoints WHERE thread_id = :t"),
                {"t": thread_id},
            ).rowcount
        logger.debug(
            "清理 checkpoint 线程 %s: %s 个 checkpoint / %s 条 writes", thread_id, cps, writes
        )
        return cps
