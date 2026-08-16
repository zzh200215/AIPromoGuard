"""Neo4j 知识图谱客户端（Phase 3 启用，W9）。

Neo4j 容器通过 `docker compose --profile graph up -d neo4j` 启动，
不在 profile 里时服务可能不可用。所有对外方法都优雅降级：
- 未配置 / 连接失败时返回空结果，不抛异常（与 LLM 降级策略一致，PRD §4.3）
- health() 返回布尔供健康检查使用
"""

import threading
from typing import Any

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    _NEO4J_AVAILABLE = True
except ImportError:  # neo4j driver 未安装时优雅降级
    _NEO4J_AVAILABLE = False
    ServiceUnavailable = Exception

_lock = threading.Lock()
_driver = None


def get_driver():
    """懒加载单例 driver，线程安全。"""
    global _driver
    if _driver is not None:
        return _driver
    with _lock:
        if _driver is None:
            if not _NEO4J_AVAILABLE:
                logger.warning("neo4j driver 未安装，知识图谱功能降级为空")
                return None
            if not settings.neo4j_uri:
                logger.warning("未配置 NEO4J_URI，知识图谱功能降级为空")
                return None
            try:
                _driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                    connection_timeout=5,
                    max_connection_lifetime=3600,
                )
                logger.info("Neo4j driver 初始化: %s", settings.neo4j_uri)
            except Exception:
                logger.exception("Neo4j driver 初始化失败")
                return None
    return _driver


def health() -> bool:
    """连通性探测：可写会话执行一次 `RETURN 1`。"""
    driver = get_driver()
    if driver is None:
        return False
    try:
        with driver.session(database="neo4j") as session:
            session.run("RETURN 1").consume()
        return True
    except Exception:
        return False


def run_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """执行 Cypher 查询并返回记录列表（dict 形式）。

    连接不可用时返回空列表（不抛异常），由调用方判断是否降级。
    """
    driver = get_driver()
    if driver is None:
        return []
    try:
        with driver.session(database="neo4j") as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]
    except ServiceUnavailable:
        logger.warning("Neo4j 服务不可用，知识图谱查询降级为空")
        return []
    except Exception:
        logger.exception("Neo4j 查询失败")
        return []


def run_cypher_strict(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """执行 Cypher 查询；连接不可用时抛出异常（供管理/导入脚本使用）。"""
    driver = get_driver()
    if driver is None:
        raise RuntimeError("Neo4j 不可用（未安装 driver 或未配置连接）")
    try:
        with driver.session(database="neo4j") as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]
    except ServiceUnavailable as exc:
        raise RuntimeError(f"Neo4j 服务不可用: {exc}") from exc


def close() -> None:
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None
