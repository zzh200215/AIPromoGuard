"""ChromaDB 实现（当前唯一向量库）。"""


import chromadb
from chromadb.config import Settings as ChromaSettings

from src.utils.config import settings

from .base import VectorStore


class ChromaVectorStore(VectorStore):
    def __init__(self, persist_dir: str | None = None) -> None:
        # 合规场景不向 Chroma 外发匿名遥测（0.5.0 的 anonymized_telemetry 开关失效，
        # 需替换 telemetry 实现为 no-op）
        self._client = chromadb.PersistentClient(
            path=persist_dir or settings.chroma_persist_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                # System 通过 chroma_product_telemetry_impl 实例化遥测客户端，
                # 替换为 no-op 实现（chroma_telemetry_impl 只是别名，不生效）
                chroma_product_telemetry_impl=(
                    "src.infrastructure.vectorstore.telemetry.NoopTelemetryClient"
                ),
            ),
        )

    def _collection(self, name: str):
        # ChromaDB 距离度量按 collection 设置；默认余弦相似度
        return self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )

    def add(
        self,
        collection: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        # upsert 而非 add：add 对已存在 id 仅告警并静默跳过，
        # 会让"重跑索引脚本覆盖更新"实际失效（MySQL 内容变了向量还停旧版）
        self._collection(collection).upsert(
            ids=[str(i) for i in ids],
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        result = self._collection(collection).query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        # ChromaDB 余弦距离 = 1 - 相似度，转为相似度便于上层使用
        items: list[dict] = []
        for i, doc_id in enumerate(result["ids"][0]):
            items.append(
                {
                    "id": doc_id,
                    "score": round(1 - result["distances"][0][i], 4),
                    "document": result["documents"][0][i],
                    "metadata": result["metadatas"][0][i] or {},
                }
            )
        return items

    def delete(self, collection: str, ids: list[str]) -> None:
        self._collection(collection).delete(ids=[str(i) for i in ids])

    def delete_all(self, collection: str) -> int:
        """整集合删除并重建（返回删除前条数）。数据源整体切换时用——按 id 删
        无法覆盖已不在上游表中的历史向量（如 --replace 换数据后 id 重排）。"""
        existed = self._collection(collection).count()
        if existed:
            self._client.delete_collection(collection)
            self._collection(collection)  # 重建空集合，保持幂等语义
        return existed

    def count(self, collection: str) -> int:
        return self._collection(collection).count()
