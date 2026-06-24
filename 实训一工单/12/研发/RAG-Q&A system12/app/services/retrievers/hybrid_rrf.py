from __future__ import annotations

from app.core.config import Settings
from app.services.retrievers.base import BaseRetriever, RetrievedChunk


class HybridRetriever(BaseRetriever):
    """可配置融合策略的混合检索器。"""

    def __init__(
        self,
        settings: Settings,
        text_retriever: BaseRetriever | None = None,
        vector_retriever: BaseRetriever | None = None,
        keyword_retriever: BaseRetriever | None = None,
        text_retriever_name: str = "fulltext",
    ) -> None:
        self.settings = settings
        self.text_retriever = text_retriever or keyword_retriever
        self.vector_retriever = vector_retriever
        self.text_retriever_name = text_retriever_name

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        if self.vector_retriever is None and self.text_retriever is None:
            return []
        if self.vector_retriever is None:
            return self.text_retriever.retrieve(
                question=question,
                top_k=top_k,
                retrieval_hints=retrieval_hints,
            )
        if self.text_retriever is None:
            return self.vector_retriever.retrieve(
                question=question,
                top_k=top_k,
                retrieval_hints=retrieval_hints,
            )

        candidate_size = max(top_k * self.settings.hybrid_candidate_multiplier, 20)

        text_results = self.text_retriever.retrieve_more(
            question=question,
            top_k=candidate_size,
            retrieval_hints=retrieval_hints,
        )
        vector_results = self.vector_retriever.retrieve_more(
            question=question,
            top_k=candidate_size,
            retrieval_hints=retrieval_hints,
        )

        if not text_results:
            return vector_results[:top_k]
        if not vector_results:
            return text_results[:top_k]

        strategy = self.settings.hybrid_fusion_strategy.strip().lower()
        if strategy in {"weighted", "weighted_sum", "weighted_average"}:
            return self._fuse_weighted(text_results, vector_results, top_k)
        if strategy in {"vote", "voting"}:
            return self._fuse_vote(text_results, vector_results, top_k)
        return self._fuse_rrf(text_results, vector_results, top_k)

    def prepare(self, selected_only: bool = False) -> None:
        if self.text_retriever is not None:
            self.text_retriever.prepare(selected_only=selected_only)
        if self.vector_retriever is not None:
            self.vector_retriever.prepare(selected_only=selected_only)

    def _fuse_rrf(
        self,
        text_results: list[RetrievedChunk],
        vector_results: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        fused_scores: dict[str, float] = {}
        merged_chunks: dict[str, RetrievedChunk] = {}
        metadata: dict[str, dict[str, object]] = {}

        for rank, item in enumerate(text_results, start=1):
            chunk_id = item.chunk.chunk_id
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank)
            merged_chunks.setdefault(chunk_id, item)
            metadata.setdefault(chunk_id, {})["text_rank"] = rank
            metadata.setdefault(chunk_id, {})["text_score_raw"] = item.score

        for rank, item in enumerate(vector_results, start=1):
            chunk_id = item.chunk.chunk_id
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank)
            merged_chunks.setdefault(chunk_id, item)
            metadata.setdefault(chunk_id, {})["vector_rank"] = rank
            metadata.setdefault(chunk_id, {})["vector_score_raw"] = item.score

        fused = [
            RetrievedChunk(
                chunk=merged_chunks[chunk_id].chunk,
                score=round(score, 6),
                metadata={
                    "fusion_strategy": "rrf",
                    "text_retriever": self.text_retriever_name,
                    **metadata.get(chunk_id, {}),
                },
            )
            for chunk_id, score in fused_scores.items()
        ]
        fused.sort(key=lambda item: item.score, reverse=True)
        return fused[:top_k]

    def _fuse_weighted(
        self,
        text_results: list[RetrievedChunk],
        vector_results: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        text_scores = self._normalized_scores(text_results)
        vector_scores = self._normalized_scores(vector_results)
        chunk_map = {item.chunk.chunk_id: item for item in [*text_results, *vector_results]}

        merged: list[RetrievedChunk] = []
        for chunk_id in set(text_scores) | set(vector_scores):
            score = (
                text_scores.get(chunk_id, 0.0) * self.settings.hybrid_fulltext_weight
                + vector_scores.get(chunk_id, 0.0) * self.settings.hybrid_vector_weight
            )
            base_item = chunk_map[chunk_id]
            merged.append(
                RetrievedChunk(
                    chunk=base_item.chunk,
                    score=round(score, 6),
                    metadata={
                        "fusion_strategy": "weighted",
                        "text_retriever": self.text_retriever_name,
                        "text_component": round(text_scores.get(chunk_id, 0.0), 6),
                        "vector_component": round(vector_scores.get(chunk_id, 0.0), 6),
                    },
                )
            )
        merged.sort(key=lambda item: item.score, reverse=True)
        return merged[:top_k]

    def _fuse_vote(
        self,
        text_results: list[RetrievedChunk],
        vector_results: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        text_scores = self._normalized_scores(text_results)
        vector_scores = self._normalized_scores(vector_results)
        text_ids = {item.chunk.chunk_id for item in text_results}
        vector_ids = {item.chunk.chunk_id for item in vector_results}
        chunk_map = {item.chunk.chunk_id: item for item in [*text_results, *vector_results]}

        merged: list[RetrievedChunk] = []
        for chunk_id in set(text_ids) | set(vector_ids):
            votes = int(chunk_id in text_ids) + int(chunk_id in vector_ids)
            if votes < self.settings.hybrid_vote_min_agreement:
                continue
            score = votes + (
                text_scores.get(chunk_id, 0.0) * self.settings.hybrid_fulltext_weight
                + vector_scores.get(chunk_id, 0.0) * self.settings.hybrid_vector_weight
            )
            merged.append(
                RetrievedChunk(
                    chunk=chunk_map[chunk_id].chunk,
                    score=round(score, 6),
                    metadata={
                        "fusion_strategy": "vote",
                        "text_retriever": self.text_retriever_name,
                        "votes": votes,
                        "text_component": round(text_scores.get(chunk_id, 0.0), 6),
                        "vector_component": round(vector_scores.get(chunk_id, 0.0), 6),
                    },
                )
            )
        merged.sort(
            key=lambda item: (
                int(item.metadata.get("votes", 0)),
                item.score,
            ),
            reverse=True,
        )
        return merged[:top_k]

    def _normalized_scores(self, results: list[RetrievedChunk]) -> dict[str, float]:
        if not results:
            return {}
        max_score = max(item.score for item in results)
        min_score = min(item.score for item in results)
        score_span = max(max_score - min_score, 1e-6)
        total = max(len(results), 1)
        normalized: dict[str, float] = {}
        for rank, item in enumerate(results, start=1):
            raw_component = (item.score - min_score) / score_span
            rank_component = (total - rank + 1) / total
            normalized[item.chunk.chunk_id] = raw_component * 0.35 + rank_component * 0.65
        return normalized


HybridRRFRetriever = HybridRetriever
