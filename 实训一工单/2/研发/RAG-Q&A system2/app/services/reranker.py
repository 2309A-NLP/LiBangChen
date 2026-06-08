"""重排序服务模块。

使用 Cross-encoder 模型（如 bge-reranker-base）对检索结果进行精细相关性打分和重排序。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RerankerService:
    """Cross-encoder reranker using bge-reranker-base."""

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        max_length: int = 512,
        top_n: int | None = None,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.max_length = max_length
        self.top_n = top_n
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """延迟加载 Cross-encoder 模型和分词器。"""
        if self._model is not None:
            return

        logger.info("Loading reranker model from %s", self.model_path)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
        self._model.to(self.device)
        self._model.eval()
        logger.info("Reranker model loaded successfully on %s", self.device)

    def rerank(
        self,
        question: str,
        chunks: list,
        top_n: int | None = None,
    ) -> list:
        """Rerank retrieved chunks by relevance score.

        Args:
            question: The user query.
            chunks: List of RetrievedChunk objects from initial retrieval.
            top_n: Ignored — callsite controls filtering via their top_k.

        Returns:
            ALL chunks reranked by cross-encoder score (descending).
            The callsite (RetrievalGenerationService) decides how many to keep.
        """
        if not chunks:
            return []

        self._load_model()

        pairs = [(question, chunk.chunk.text) for chunk in chunks]

        import torch

        # 分批推理，避免显存溢出
        scores = []
        batch_size = 32
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits.squeeze(-1)
                batch_scores = logits.cpu().tolist()
                if isinstance(batch_scores, float):
                    batch_scores = [batch_scores]
                scores.extend(batch_scores)

        from app.services.retrievers.base import RetrievedChunk

        reranked = []
        for chunk, score in zip(chunks, scores):
            reranked.append(
                RetrievedChunk(chunk=chunk.chunk, score=round(float(score), 4))
            )

        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked
