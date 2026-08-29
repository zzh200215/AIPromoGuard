"""LLM 精确匹配响应缓存（P5）。

为什么是"精确匹配"而不是字面意义的语义（相似度）缓存：合规判定对输入措辞
极度敏感——"预期年化收益5%"与"预期年化收益5%左右，可能有波动"一个违规一个
合规，embedding 相似度分不开这两种文本；用相似度阈值决定"是否复用一次合规
判定"是在拿正确性换成本。本实现只在 (prompt, 模型, 温度, json_mode) 完全一致
时复用响应，语义缓存作为**有意不采纳**的方案记录在案。

- 缓存键：sha256(schema 版本 + 模型 + 温度 + json_mode + messages 规范化 JSON)。
  知识库更新会改变检索上下文 → messages 变化 → 自然失效，无需手工清理。
- 降级：任何存储异常都视为缓存未命中，绝不影响 LLM 主路径。
- 开关：workflow.llm_cache（缺省 false，与 agentic_retrieval / rerank 同为
  显式可选增强）。当前接入点：regulation_match 的 agentic 充分性评估；
  llm_scan 全块扫描为最大收益点，待其所在文件解冻后按同模式接入（两行）。
"""

import hashlib
import json
from datetime import datetime, timedelta

from src.core.llm.client import CompletionResult
from src.infrastructure.database.mysql import SessionLocal
from src.models import LlmCache
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_SCHEMA_VERSION = "v1"
DEFAULT_TTL_DAYS = 30


def cache_key(messages: list[dict], temperature: float | None, json_mode: bool) -> str:
    """缓存键：与"模型 + 解码参数 + 完整 prompt"一一对应。"""
    payload = json.dumps(
        {
            "v": CACHE_SCHEMA_VERSION,
            "model": settings.llm_model,
            "temp": temperature,
            "json": json_mode,
            "messages": messages,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hit(key_hash: str, now: datetime) -> CompletionResult | None:
    """读缓存并累计命中数；未命中/过期/存储异常一律返回 None。"""
    try:
        db = SessionLocal()
        try:
            row = db.get(LlmCache, key_hash)
            if row is None or row.expires_at <= now:
                return None
            row.hits += 1
            db.commit()
            return CompletionResult(
                content=row.response, model=row.model, usage=row.usage or {}
            )
        finally:
            db.close()
    except Exception:
        logger.exception("LLM 缓存读取失败，按未命中处理")
        return None


def _save(key_hash: str, result: CompletionResult, ttl_days: int, now: datetime) -> None:
    """写缓存；失败仅记日志（缓存永不影响主路径）。"""
    try:
        db = SessionLocal()
        try:
            db.merge(
                LlmCache(
                    key_hash=key_hash,
                    model=result.model,
                    response=result.content,
                    usage=result.usage,
                    hits=0,
                    created_at=now,
                    expires_at=now + timedelta(days=ttl_days),
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("LLM 缓存写入失败（忽略）")


class CachedLLM:
    """QwenClient 透明缓存包装：complete/acomplete 走缓存，其余属性委托内层。

    用法：`llm = CachedLLM(get_llm())`——对调用方完全透明（同接口）。
    """

    def __init__(self, inner, ttl_days: int = DEFAULT_TTL_DAYS):
        self._inner = inner
        self._ttl_days = ttl_days

    def complete(
        self, messages: list[dict], temperature: float | None = None, json_mode: bool = False
    ) -> CompletionResult:
        key = cache_key(messages, temperature, json_mode)
        now = datetime.now()
        hit = _hit(key, now)
        if hit is not None:
            logger.info("LLM 缓存命中（key=%s…）", key[:12])
            return hit
        result = self._inner.complete(messages, temperature, json_mode=json_mode)
        _save(key, result, self._ttl_days, now)
        return result

    async def acomplete(
        self, messages: list[dict], temperature: float | None = None, json_mode: bool = False
    ) -> CompletionResult:
        key = cache_key(messages, temperature, json_mode)
        now = datetime.now()
        hit = _hit(key, now)
        if hit is not None:
            logger.info("LLM 缓存命中（key=%s…）", key[:12])
            return hit
        result = await self._inner.acomplete(messages, temperature, json_mode=json_mode)
        _save(key, result, self._ttl_days, now)
        return result

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        return self.complete(messages, temperature).content

    def __getattr__(self, name):
        return getattr(self._inner, name)


def cache_stats() -> dict:
    """缓存规模与命中统计（管理 CLI 用）。"""
    db = SessionLocal()
    try:
        rows = db.query(LlmCache).all()
        now = datetime.now()
        return {
            "entries": len(rows),
            "active": sum(1 for r in rows if r.expires_at > now),
            "total_hits": sum(r.hits for r in rows),
        }
    finally:
        db.close()


def clear_expired() -> int:
    """删除过期条目，返回删除数。"""
    db = SessionLocal()
    try:
        deleted = db.query(LlmCache).filter(LlmCache.expires_at <= datetime.now()).delete()
        db.commit()
        return deleted
    finally:
        db.close()


def clear_all() -> int:
    """清空全部缓存，返回删除数（提示词/模型升级后使用）。"""
    db = SessionLocal()
    try:
        deleted = db.query(LlmCache).delete()
        db.commit()
        return deleted
    finally:
        db.close()
