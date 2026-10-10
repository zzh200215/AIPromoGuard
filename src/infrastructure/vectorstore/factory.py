"""向量存储工厂：ChromaDB 为当前唯一实现（Milvus 死分支已按 PR-8 清理）。"""

from functools import lru_cache

from src.utils.config import settings

from .base import VectorStore


@lru_cache
def get_vector_store() -> VectorStore:
    # 唯一实现为 chroma。仍校验配置值：历史文档预留过 milvus，.env 残留该值时应
    # 响亮报错而非静默降级（扩展点需要时再引入，见 README 已知限制）。
    store_type = settings.vector_store_type
    if store_type != "chroma":
        raise ValueError(
            f"不支持的向量库类型: {store_type}（当前唯一实现为 chroma，见 README 已知限制）"
        )

    from .chroma import ChromaVectorStore

    return ChromaVectorStore()
