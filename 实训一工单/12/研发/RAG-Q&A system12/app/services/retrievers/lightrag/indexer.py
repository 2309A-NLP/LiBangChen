from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app.core.config import LightRAGSettings
from app.services.retrievers.lightrag.client import LightRAGClient
from app.services.retrievers.lightrag.schemas import (
    IndexStatus,
    LightRAGQueryMode,
    LightRAGQueryRequest,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int], None]


class LightRAGIndexer:
    """Offline PDF-to-LightRAG graph indexing helper."""

    def __init__(
        self,
        settings: LightRAGSettings,
        client: LightRAGClient | None = None,
    ) -> None:
        self.settings = settings
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

    def index_documents(
        self,
        pdf_paths: list[str | Path],
        *,
        force_rebuild: bool = False,
        incremental: bool = False,
        max_pages_per_pdf: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> IndexStatus:
        self.client.require_healthy()
        if not force_rebuild and not incremental:
            status = self.client.get_index_status()
            if status.total_documents > 0 or status.total_chunks > 0:
                logger.info(
                    "LightRAG index already exists: documents=%s chunks=%s",
                    status.total_documents,
                    status.total_chunks,
                )
                return status

        all_chunks: list[tuple[str, str]] = []
        self._report(progress_callback, "extracting", 0, len(pdf_paths))
        for index, pdf_path in enumerate(pdf_paths, start=1):
            path = Path(pdf_path)
            file_id = path.stem
            text = self._extract_text(path, max_pages=max_pages_per_pdf)
            chunks = self._split_text(text, file_id)
            logger.info("%s: %s characters -> %s chunks", file_id, len(text), len(chunks))
            all_chunks.extend(chunks)
            self._report(progress_callback, "extracting", index, len(pdf_paths))

        self._report(progress_callback, "inserting", 0, len(all_chunks))
        results = self.client.batch_insert(
            texts=all_chunks,
            entity_types=self.settings.entity_types,
            relation_types=self.settings.relation_types,
            concurrency=self.settings.max_parallel_insert,
        )
        errors = [str(item) for item in results if isinstance(item, Exception)][:20]
        self._report(progress_callback, "inserting", len(all_chunks) - len(errors), len(all_chunks))

        status = self.client.get_index_status()
        if status.working_dir == "unknown":
            status.working_dir = self.settings.working_dir
        status.errors = errors
        return status

    def validate_sample(self, test_queries: list[str]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for query in test_queries:
            try:
                response = self.client.query(
                    LightRAGQueryRequest(
                        query=query,
                        mode=LightRAGQueryMode.MIX,
                        top_k=5,
                    )
                )
                results.append(
                    {
                        "query": query,
                        "answer": response.answer,
                        "chunks": [
                            {
                                "content": chunk.content[:300],
                                "score": round(chunk.score, 4),
                                "file_id": chunk.file_id,
                            }
                            for chunk in response.chunks
                        ],
                    }
                )
            except Exception as exc:
                results.append({"query": query, "error": str(exc)})
        return results

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _extract_text(self, pdf_path: Path, max_pages: int | None = None) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required to build the LightRAG index") from exc

        reader = PdfReader(str(pdf_path))
        pages = reader.pages[:max_pages] if max_pages is not None else reader.pages
        page_texts = [page.extract_text() or "" for page in pages]
        return "\n\n".join(page_texts)

    def _split_text(self, text: str, file_id: str) -> list[tuple[str, str]]:
        chunk_size = self.settings.chunk_size
        chunk_overlap = min(self.settings.chunk_overlap, max(chunk_size - 1, 0))
        separators = ["\n\n", "\n", "\u3002", "\uff1b", ")", "\uff09"]
        chunks: list[tuple[str, str]] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                for separator in separators:
                    search_end = min(end + chunk_overlap + len(separator), len(text))
                    position = text.rfind(separator, start, search_end)
                    if position > start + chunk_size // 2:
                        end = position + len(separator)
                        break
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append((chunk_text, file_id))
            if end >= len(text):
                break
            start = max(end - chunk_overlap, start + 1)
        return chunks

    @staticmethod
    def _report(callback: ProgressCallback | None, stage: str, done: int, total: int) -> None:
        if callback is None:
            return
        try:
            callback(stage, done, total)
        except Exception:
            logger.debug("LightRAG progress callback failed.", exc_info=True)
