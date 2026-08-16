"""FastEmbed 实现：ONNX 轻量推理（bge-small-zh-v1.5，512 维），免 torch。

模型缓存目录可配置（默认 data/models/fastembed），与容器卷挂载共享，
避免重复下载。
"""

from fastembed import TextEmbedding

from src.infrastructure.embedding.base import Embedder
from src.utils.config import settings


class FastEmbedEmbedder(Embedder):
    name = "fastembed-bge-small-zh"

    def __init__(self, model_name: str | None = None, cache_dir: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self.dim = settings.embedding_dim
        self._model = TextEmbedding(
            self.model_name, cache_dir=cache_dir or settings.embedding_cache_dir
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]
