"""Embedding 抽象接口：统一文本向量化，供向量库与召回使用。"""

from abc import ABC, abstractmethod


class Embedder(ABC):
    name: str = "base"
    dim: int = 512

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与输入等长的向量列表。"""
