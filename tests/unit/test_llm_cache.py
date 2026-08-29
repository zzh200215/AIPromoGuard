"""LLM 精确匹配缓存的单元测试（离线：SQLite 内存库 + FakeLLM，不连 MySQL）。

覆盖：缓存键稳定性与敏感性 / 命中与未命中 / TTL 过期 / 存储故障降级 /
async 路径 / chat 与属性委托 / 统计与清理 / 节点接入开关。
"""

import asyncio
from types import SimpleNamespace

import pytest
import src.core.agents.nodes.regulation_match as rm_node
import src.services.llm_cache as lc
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.core.llm.client import CompletionResult
from src.infrastructure.database.mysql import Base
from src.models import LlmCache
from src.services import agentic_retrieval, regulation_service
from src.services.llm_cache import CachedLLM, cache_key

_MESSAGES = [{"role": "user", "content": "评估这段文本"}]


class FakeInner:
    def __init__(self):
        self.calls = 0
        self.any_attr = 42

    def complete(self, messages, temperature=None, json_mode=False):
        self.calls += 1
        return CompletionResult(
            content=f"resp-{self.calls}", model="qwen-plus", usage={"total_tokens": 7, "calls": 1}
        )

    async def acomplete(self, messages, temperature=None, json_mode=False):
        return self.complete(messages, temperature, json_mode)


@pytest.fixture()
def cache_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine, tables=[LlmCache.__table__])
    monkeypatch.setattr(lc, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    return engine


# ---------- 缓存键 ----------


def test_cache_key_stable_and_sensitive():
    assert cache_key(_MESSAGES, 0.2, False) == cache_key(_MESSAGES, 0.2, False)
    other = [{"role": "user", "content": "别的"}]
    assert cache_key(_MESSAGES, 0.2, False) != cache_key(other, 0.2, False)
    assert cache_key(_MESSAGES, 0.2, False) != cache_key(_MESSAGES, 0.7, False)
    assert cache_key(_MESSAGES, 0.2, False) != cache_key(_MESSAGES, 0.2, True)


# ---------- 命中 / 未命中 / TTL ----------


def test_second_identical_call_hits_cache(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner)
    first = llm.complete(_MESSAGES, 0.2)
    second = llm.complete(_MESSAGES, 0.2)

    assert inner.calls == 1
    assert second.content == first.content == "resp-1"
    assert lc.cache_stats() == {"entries": 1, "active": 1, "total_hits": 1}


def test_different_inputs_do_not_collide(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner)
    llm.complete(_MESSAGES, 0.2)
    llm.complete([{"role": "user", "content": "另一个 prompt"}], 0.2)
    assert inner.calls == 2
    assert lc.cache_stats()["entries"] == 2


def test_ttl_expiry_forces_miss(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner, ttl_days=0)  # 写入即过期
    llm.complete(_MESSAGES, 0.2)
    llm.complete(_MESSAGES, 0.2)
    assert inner.calls == 2
    assert lc.cache_stats()["active"] == 0


def test_storage_failure_degrades_to_inner(cache_db, monkeypatch):
    def broken_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(lc, "SessionLocal", broken_session)
    inner = FakeInner()
    llm = CachedLLM(inner)
    assert llm.complete(_MESSAGES, 0.2).content == "resp-1"
    assert llm.complete(_MESSAGES, 0.2).content == "resp-2"  # 读写均降级，主路径不受影响
    assert inner.calls == 2


# ---------- async / 委托 ----------


def test_acomplete_uses_cache(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner)
    first = asyncio.run(llm.acomplete(_MESSAGES, 0.2))
    second = asyncio.run(llm.acomplete(_MESSAGES, 0.2))
    assert inner.calls == 1 and second.content == first.content


def test_chat_and_attribute_delegation(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner)
    assert llm.chat(_MESSAGES) == "resp-1"
    assert llm.chat(_MESSAGES) == "resp-1"  # chat 复用 complete 的缓存
    assert inner.calls == 1
    assert llm.any_attr == 42  # 其余属性透明委托内层


# ---------- 统计与清理 ----------


def test_stats_and_clear(cache_db):
    inner = FakeInner()
    llm = CachedLLM(inner)
    llm.complete(_MESSAGES, 0.2)
    llm.complete(_MESSAGES, 0.2)

    assert lc.cache_stats()["total_hits"] == 1
    assert lc.clear_expired() == 0  # 未过期无删除
    assert lc.clear_all() == 1
    assert lc.cache_stats()["entries"] == 0


# ---------- 节点接入开关 ----------


def test_regulation_match_wraps_llm_when_cache_enabled(monkeypatch):
    monkeypatch.setattr(rm_node, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(regulation_service, "search_hybrid", lambda *a, **k: [])
    sentinel = SimpleNamespace()
    monkeypatch.setattr(rm_node, "get_llm", lambda: sentinel)
    monkeypatch.setattr(
        rm_node,
        "settings",
        SimpleNamespace(
            app_config=lambda key: {
                "agentic_retrieval": True,
                "llm_cache": True,
                "graph_recall": False,
                "regulation_top_k": 5,
            }
        ),
    )
    captured = {}

    def fake_refine(db, llm, *args, **kwargs):
        captured["llm"] = llm
        return [], {"rounds": 1, "added": 0}

    monkeypatch.setattr(agentic_retrieval, "agentic_refine", fake_refine)
    rm_node.regulation_match({"text": "文本", "domain": None})

    assert isinstance(captured["llm"], CachedLLM)
    assert captured["llm"]._inner is sentinel


def test_regulation_match_no_wrap_when_cache_disabled(monkeypatch):
    monkeypatch.setattr(rm_node, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(regulation_service, "search_hybrid", lambda *a, **k: [])
    sentinel = SimpleNamespace()
    monkeypatch.setattr(rm_node, "get_llm", lambda: sentinel)
    monkeypatch.setattr(
        rm_node,
        "settings",
        SimpleNamespace(
            app_config=lambda key: {
                "agentic_retrieval": True,
                "graph_recall": False,
                "regulation_top_k": 5,
            }
        ),
    )
    captured = {}

    def fake_refine(db, llm, *args, **kwargs):
        captured["llm"] = llm
        return [], {"rounds": 1, "added": 0}

    monkeypatch.setattr(agentic_retrieval, "agentic_refine", fake_refine)
    rm_node.regulation_match({"text": "文本", "domain": None})
    assert captured["llm"] is sentinel
