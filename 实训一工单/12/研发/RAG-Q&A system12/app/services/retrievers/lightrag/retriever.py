from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import LightRAGSettings
from app.services.document_ingestion import DocumentChunk, DocumentIngestionService
from app.services.retrievers.base import BaseRetriever, RetrievedChunk
from app.services.retrievers.lightrag.client import LightRAGClient
from app.services.retrievers.lightrag.errors import LightRAGQueryError
from app.services.retrievers.lightrag.schemas import (
    LightRAGQueryMode,
    LightRAGQueryRequest,
    LightRAGQueryResponse,
)

logger = logging.getLogger(__name__)

MODE_MAP: dict[str, LightRAGQueryMode] = {
    "lightrag_mix": LightRAGQueryMode.MIX,
    "lightrag_local": LightRAGQueryMode.LOCAL,
    "lightrag_global": LightRAGQueryMode.GLOBAL,
    "lightrag_hybrid": LightRAGQueryMode.HYBRID,
}


class LightRAGRetriever(BaseRetriever):
    """BaseRetriever adapter for the LightRAG knowledge-graph sidecar."""

    def __init__(
        self,
        settings: LightRAGSettings,
        document_ingestion_service: DocumentIngestionService | None = None,
        retrieval_mode: str = "lightrag_mix",
        client: LightRAGClient | None = None,
    ) -> None:
        self.settings = settings
        self.document_ingestion_service = document_ingestion_service
        self.retrieval_mode = retrieval_mode
        self._client = client

    @property
    def client(self) -> LightRAGClient:
        if self._client is None:
            self._client = LightRAGClient(
                base_url=self.settings.base_url,
                api_key=self.settings.api_key,
                timeout=self.settings.timeout,
                max_retries=self.settings.insert_retry,
            )
        return self._client

    def prepare(self, selected_only: bool = False) -> None:
        return None

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        mode = self._resolve_mode(self.retrieval_mode)
        file_ids = self._resolve_file_ids(retrieval_hints)
        request = LightRAGQueryRequest(
            query=question,
            mode=mode,
            top_k=top_k or self.settings.top_k,
            file_ids=file_ids,
            include_references=True,
        )
        logger.info(
            "LightRAG query mode=%s top_k=%s file_scope=%s",
            mode.value,
            request.top_k,
            len(file_ids) if file_ids else "all",
        )
        self.client.require_healthy()
        try:
            response = self.client.query(request)
        except LightRAGQueryError:
            raise
        except Exception as exc:
            raise LightRAGQueryError(str(exc)) from exc
        return self._to_retrieved_chunks(response, requested_file_ids=file_ids)[:top_k]

    def retrieve_more(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        return self.retrieve(
            question=question,
            top_k=max(top_k, self.settings.top_k),
            retrieval_hints=retrieval_hints,
        )[:top_k]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _resolve_mode(self, retrieval_mode: str | None) -> LightRAGQueryMode:
        mode = (retrieval_mode or "").strip().lower()
        if not mode:
            mode = f"lightrag_{self.settings.default_mode.strip().lower()}"
        if mode not in MODE_MAP:
            raise ValueError(
                f"Unsupported LightRAG retrieval_mode: {retrieval_mode}. "
                f"Available values: {sorted(MODE_MAP)}"
            )
        return MODE_MAP[mode]

    def _resolve_file_ids(self, retrieval_hints: dict[str, object] | None) -> list[str] | None:
        source_files = self._source_files_from_hints(retrieval_hints)
        if source_files is None and self.document_ingestion_service is not None:
            try:
                selected_sources = self.document_ingestion_service.status().get("selected_sources", [])
                if isinstance(selected_sources, list):
                    source_files = [item for item in selected_sources if isinstance(item, str)]
            except Exception:
                source_files = None
        if not source_files:
            return None
        file_ids = []
        for source_file in source_files:
            stem = Path(source_file).stem.strip()
            if stem and stem not in file_ids:
                file_ids.append(stem)
        return file_ids or None

    @staticmethod
    def _source_files_from_hints(retrieval_hints: dict[str, object] | None) -> list[str] | None:
        if not retrieval_hints:
            return None
        value = retrieval_hints.get("source_files") or retrieval_hints.get("sources")
        if not isinstance(value, list):
            return None
        return [item for item in value if isinstance(item, str) and item.strip()]

    def _to_retrieved_chunks(
        self,
        response: LightRAGQueryResponse,
        requested_file_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        results: list[RetrievedChunk] = []
        requested_sources = self._normalize_source_set(requested_file_ids)
        for light_chunk in response.chunks:
            if light_chunk.score < self.settings.min_score:
                continue
            metadata: dict[str, Any] = dict(light_chunk.metadata)
            if requested_sources:
                source_candidates = self._source_candidates(light_chunk.file_id, metadata)
                if not source_candidates:
                    metadata["lightrag_source_filter_unavailable"] = True
                elif source_candidates.isdisjoint(requested_sources):
                    continue
                else:
                    metadata["lightrag_source_filter_matched"] = True
            metadata.update(
                {
                    "retriever": "lightrag",
                    "retrieval_method": f"lightrag_{response.mode.value}",
                    "lightrag_answer": response.answer,
                    "lightrag_total_tokens": response.total_tokens,
                }
            )
            page_number = self._coerce_page_number(metadata.get("page_number") or metadata.get("page"))
            source_id = str(light_chunk.file_id or metadata.get("source_id") or "lightrag")
            results.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id=light_chunk.chunk_id,
                        source_id=source_id,
                        page_number=page_number,
                        text=light_chunk.content,
                    ),
                    score=light_chunk.score,
                    metadata=metadata,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results

    @classmethod
    def _source_candidates(cls, file_id: str | None, metadata: dict[str, Any]) -> set[str]:
        raw_values = [
            file_id,
            metadata.get("file_source"),
            metadata.get("file_id"),
            metadata.get("file_path"),
            metadata.get("source_id"),
            metadata.get("source"),
        ]
        candidates: set[str] = set()
        for value in raw_values:
            if isinstance(value, list):
                for item in value:
                    candidates.update(cls._normalize_source_value(item))
                continue
            candidates.update(cls._normalize_source_value(value))
        return candidates

    @classmethod
    def _normalize_source_set(cls, values: list[str] | None) -> set[str]:
        if not values:
            return set()
        normalized: set[str] = set()
        for value in values:
            normalized.update(cls._normalize_source_value(value))
        return normalized

    @staticmethod
    def _normalize_source_value(value: object) -> set[str]:
        if value is None:
            return set()
        text = str(value).strip()
        if not text:
            return set()
        path = Path(text)
        stem = path.stem.strip().lower()
        name = path.name.strip().lower()
        lowered = text.strip().lower()
        return {item for item in {lowered, name, stem} if item}

    @staticmethod
    def _coerce_page_number(value: object) -> int | None:
        if value is None:
            return None
        try:
            page_number = int(value)
        except (TypeError, ValueError):
            return None
        return page_number if page_number > 0 else None
