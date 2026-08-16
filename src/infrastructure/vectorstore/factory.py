"""向量存储工厂：根据配置返回对应实现。"""

from functools import lru_cache

from src.utils.config import settings

from .base import VectorStore


@lru_cache
def get_vector_store() -> VectorStore:
    store_type = settings.vector_store_type
    if store_type == "chroma":
        from .chroma import ChromaVectorStore

        return ChromaVectorStore()

    if store_type == "milvus":
        raise NotImplementedError(
            "Milvus 实现尚未接入；当前 MVP 使用 ChromaDB（VECTOR_STORE_TYPE=chroma）。"
        )

    raise ValueError(f"未知向量库类型: {store_type}（可选: chroma | milvus）")
