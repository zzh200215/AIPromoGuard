"""Embedding 工厂：返回单例 embedder，后续可扩展 OpenAI/DashScope 等实现。"""

from functools import lru_cache

from src.infrastructure.embedding.base import Embedder
from src.infrastructure.embedding.fastembed_impl import FastEmbedEmbedder


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedEmbedder()
