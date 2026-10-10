"""向量存储抽象接口：业务层只依赖本接口，当前唯一实现为 ChromaDB。

（历史预留的 Milvus 分支已按 PR-8 清理——知识库扩容未列入范围，实现后无真实
工作负载验证；扩展点需要时再引入，见 README 已知限制。）
"""

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
        """写入向量及其关联文本（按 id upsert：已存在则覆盖更新）。"""

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

    def delete_all(self, collection: str) -> int:
        """整集合清空（返回删除前条数），默认 NotImplemented 由子类覆写。"""
        raise NotImplementedError

    @abstractmethod
    def count(self, collection: str) -> int:
        """返回集合内向量数量。"""
