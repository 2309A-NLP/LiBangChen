from __future__ import annotations

"""混合检索器：基于 RRF（Reciprocal Rank Fusion）融合关键词和向量检索结果。

同时运行关键词检索和向量检索，通过 RRF 算法对两路结果进行融合排序，
兼顾精确匹配和语义相似性的优势。
"""

from app.core.config import Settings
from app.services.retrievers.base import BaseRetriever, RetrievedChunk


class HybridRRFRetriever(BaseRetriever):
    """基于 RRF 的混合检索器。

    分别调用关键词检索器和向量检索器获取候选集，再通过 RRF 公式
    ``score += 1 / (k + rank)`` 融合两路排名，返回 top_k 结果。
    """
    def __init__(
        self,
        settings: Settings,
        keyword_retriever: BaseRetriever,
        vector_retriever: BaseRetriever,
    ) -> None:
        self.settings = settings
        self.keyword_retriever = keyword_retriever
        self.vector_retriever = vector_retriever

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        candidate_size = max(top_k * 5, 20)

        keyword_results = self.keyword_retriever.retrieve_more(
            question=question,
            top_k=candidate_size,
            retrieval_hints=retrieval_hints,
        )
        vector_results = self.vector_retriever.retrieve_more(
            question=question,
            top_k=candidate_size,
            retrieval_hints=retrieval_hints,
        )

        rrf_scores: dict[str, float] = {}
        merged_chunks: dict[str, RetrievedChunk] = {}

        for rank, item in enumerate(keyword_results, start=1):
            chunk_id = item.chunk.chunk_id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank)
            merged_chunks.setdefault(chunk_id, item)

        for rank, item in enumerate(vector_results, start=1):
            chunk_id = item.chunk.chunk_id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank)
            merged_chunks.setdefault(chunk_id, item)

        fused = [
            RetrievedChunk(chunk=merged_chunks[chunk_id].chunk, score=round(score, 6))
            for chunk_id, score in rrf_scores.items()
        ]
        fused.sort(key=lambda item: item.score, reverse=True)
        return fused[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        self.keyword_retriever.prepare(selected_only=selected_only)
        self.vector_retriever.prepare(selected_only=selected_only)
