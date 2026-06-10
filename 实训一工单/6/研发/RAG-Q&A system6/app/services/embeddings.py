"""向量嵌入服务模块。

基于 SentenceTransformer 模型，为文档和查询生成归一化向量表示。
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings


class EmbeddingService:
    """向量嵌入服务，封装 SentenceTransformer 模型的加载与推理。"""
    def __init__(self, settings: Settings) -> None:
        """初始化嵌入服务，加载指定模型到指定设备。"""
        self.settings = settings
        self._model = self._load_model(settings.embedding_model_name, settings.embedding_device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量将文本列表编码为归一化向量。"""
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=self.settings.embedding_batch_size,
            show_progress_bar=False,
        )
        normalized_vectors: list[list[float]] = []
        for vector in vectors:
            if hasattr(vector, "tolist"):
                normalized_vectors.append(vector.tolist())
            else:
                normalized_vectors.append(list(vector))
        return normalized_vectors

    def embed_query(self, text: str) -> list[float]:
        """将单条查询文本编码为向量。"""
        vectors = self.embed_documents([text])
        return vectors[0] if vectors else []

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_model(model_name: str, device: str):
        """加载 SentenceTransformer 模型，使用 LRU 缓存避免重复加载。"""
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name, device=device)
