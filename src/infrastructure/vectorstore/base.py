"""向量存储抽象接口：MVP 用 ChromaDB 实现，预留 Milvus 平滑切换。"""

from abc import ABC, abstractmethod


class VectorStore(ABC):
    """统一向量检索接口，业务层只依赖本接口。"""

    @abstractmethod
    def add(
        self,
        collection: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        """写入向量及其关联文本。"""

    @abstractmethod
    def query(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        """语义检索，返回 [{id, score, document, metadata}]，按相似度降序。"""

    @abstractmethod
    def delete(self, collection: str, ids: list[str]) -> None:
        """按 id 删除向量。"""

    @abstractmethod
    def count(self, collection: str) -> int:
        """返回集合内向量数量。"""
