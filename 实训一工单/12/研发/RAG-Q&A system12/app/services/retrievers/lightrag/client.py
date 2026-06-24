from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time
from typing import Any

import httpx

from app.services.retrievers.lightrag.errors import (
    LightRAGInsertError,
    LightRAGQueryError,
    LightRAGUnavailableError,
)
from app.services.retrievers.lightrag.schemas import (
    IndexStatus,
    LightRAGChunk,
    LightRAGInsertRequest,
    LightRAGQueryMode,
    LightRAGQueryRequest,
    LightRAGQueryResponse,
)

logger = logging.getLogger(__name__)


class LightRAGClient:
    """Synchronous HTTP client for a LightRAG sidecar server."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: int = 300,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(max_retries, 1)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(timeout),
                write=30.0,
                pool=10.0,
            ),
        )

    def close(self) -> None:
        self._client.close()

    def health_check(self) -> bool:
        try:
            response = self._client.get("/health", timeout=10.0)
            if response.is_success:
                data = response.json()
                # LightRAG API returns {"status": "healthy", ...}
                return data.get("status") == "healthy"
            return False
        except Exception:
            return False

    def require_healthy(self) -> None:
        if not self.health_check():
            raise LightRAGUnavailableError(self.base_url)

    def insert(self, request: LightRAGInsertRequest) -> dict[str, Any]:
        last_error: Exception | None = None
        # LightRAG API uses /documents/text with {text, file_source, chunking}
        payload: dict[str, Any] = {
            "text": request.text,
            "file_source": request.file_id,
        }
        # entity_types / relation_types are LightRAG SDK parameters,
        # not supported by the HTTP API server. Configure them server-side if needed.
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.post(
                    "/documents/text",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not self._is_retryable(exc):
                    break
                delay = min(2**attempt, 30)
                logger.warning(
                    "LightRAG insert retry %s/%s: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                time.sleep(delay)
        raise LightRAGInsertError(request.file_id, str(last_error)) from last_error

    def batch_insert(
        self,
        texts: list[tuple[str, str]],
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        concurrency: int = 4,
    ) -> list[dict[str, Any] | Exception]:
        # LightRAG API supports batch insert via /documents/texts
        # with {texts: [...], file_sources: [...]}
        all_texts = [t for t, _ in texts]
        all_sources = [f for _, f in texts]
        # Keep unique sources while preserving order
        seen: set[str] = set()
        file_sources: list[str] = []
        for s in all_sources:
            if s not in seen:
                file_sources.append(s)
                seen.add(s)

        payload: dict[str, Any] = {
            "texts": all_texts,
        }
        if file_sources:
            # Map each text to its source index
            # The API may use file_sources to track provenance
            payload["file_sources"] = all_sources

        try:
            response = self._client.post(
                "/documents/texts",
                json=payload,
                timeout=float(min(max(self.timeout * 2, 60), 600)),
            )
            response.raise_for_status()
            result = response.json()
            # Return per-text status; if API returns a single summary, replicate it
            status = result.get("status", "unknown")
            track_id = result.get("track_id", "")
            return [{"status": status, "track_id": track_id} for _ in texts]
        except Exception as exc:
            logger.error("LightRAG batch insert failed: %s", exc)
            return [exc for _ in texts]

    def query(self, request: LightRAGQueryRequest) -> LightRAGQueryResponse:
        # Use /query/data to get structured KG results (entities + relationships)
        # rather than /query which returns LLM-generated answer with null-content refs
        payload = {
            "query": request.query,
            "mode": request.mode.value,
        }
        # file_ids filtering not supported by LightRAG query API directly;
        # we post-filter in the retriever layer instead.

        try:
            response = self._client.post(
                "/query/data",
                json=payload,
                timeout=float(min(max(self.timeout, 1), 300)),
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise LightRAGQueryError(f"HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.TimeoutException as exc:
            raise LightRAGQueryError(f"timeout after {self.timeout}s") from exc
        except Exception as exc:
            raise LightRAGQueryError(str(exc)) from exc

        try:
            return self._parse_query_response(raw, request)
        except Exception as exc:
            raise LightRAGQueryError(f"unexpected response format: {exc}") from exc

    def get_index_status(self) -> IndexStatus:
        try:
            response = self._client.get("/index/status", timeout=30.0)
            response.raise_for_status()
            data = response.json()
            if "data" in data and isinstance(data["data"], dict):
                data = data["data"]
            return IndexStatus(**data)
        except Exception:
            logger.warning("GET /index/status unavailable; returning empty LightRAG status.")
            return IndexStatus(working_dir="unknown")

    def _parse_query_response(
        self, raw: dict[str, Any], request: LightRAGQueryRequest | None = None
    ) -> LightRAGQueryResponse:
        # LightRAG /query/data returns:
        # {"status":"success","message":"...","data":{"entities":[...],"relationships":[...]}}
        data = raw.get("data") or {}
        entities: list[dict[str, Any]] = data.get("entities") or []
        relationships: list[dict[str, Any]] = data.get("relationships") or []

        # /query returns:
        # {"response":"answer text...","references":[{"reference_id":"1","file_path":"...","content":null}]}
        llm_answer = raw.get("response") or data.get("response")
        references = raw.get("references") or data.get("references") or []

        chunks: list[LightRAGChunk] = []
        seen_contents: set[str] = set()

        # Convert entities → chunks (entity descriptions are the most useful for retrieval)
        for ent in entities:
            source_id = str(ent.get("source_id") or ent.get("entity_name") or "")
            file_id = (
                ent.get("file_source")
                or ent.get("file_id")
                or ent.get("file_path")
                or ent.get("source")
            )
            desc = str(ent.get("description") or "")
            ent_type = str(ent.get("entity_type") or "")
            ent_name = str(ent.get("entity_name") or "")

            content_parts = [p for p in [ent_name, ent_type, desc] if p and p != "UNKNOWN"]
            content = " | ".join(content_parts) if content_parts else ent_name

            if content and content not in seen_contents:
                seen_contents.add(content)
                chunks.append(
                    LightRAGChunk(
                        chunk_id=f"ent-{source_id}",
                        content=content,
                        score=float(ent.get("weight", 0.8)),
                        file_id=file_id,
                        metadata={
                            "lightrag_type": "entity",
                            "entity_name": ent_name,
                            "entity_type": ent_type,
                            "source_id": source_id,
                            "file_source": ent.get("file_source"),
                            "file_id": ent.get("file_id"),
                            "file_path": ent.get("file_path"),
                            "created_at": ent.get("created_at"),
                        },
                    )
                )

        # Convert relationships → chunks
        for rel in relationships:
            source_id = str(rel.get("source_id") or "")
            file_id = (
                rel.get("file_source")
                or rel.get("file_id")
                or rel.get("file_path")
                or rel.get("source")
            )
            src = str(rel.get("src_id") or "")
            tgt = str(rel.get("tgt_id") or "")
            desc = str(rel.get("description") or "")
            keywords = str(rel.get("keywords") or "")
            weight = float(rel.get("weight", 0.5))

            content = f"{src} → {tgt}: {desc}"
            if keywords:
                content += f" [{keywords}]"

            if content and content not in seen_contents:
                seen_contents.add(content)
                chunks.append(
                    LightRAGChunk(
                        chunk_id=f"rel-{source_id or src}-{tgt}",
                        content=content,
                        score=min(weight, 1.0),
                        file_id=file_id,
                        metadata={
                            "lightrag_type": "relationship",
                            "src_entity": src,
                            "tgt_entity": tgt,
                            "keywords": keywords,
                            "source_id": source_id,
                            "file_source": rel.get("file_source"),
                            "file_id": rel.get("file_id"),
                            "file_path": rel.get("file_path"),
                            "created_at": rel.get("created_at"),
                        },
                    )
                )

        # Last resort: use /query references (may have null content)
        if not chunks and isinstance(references, list):
            for idx, ref in enumerate(references):
                if not isinstance(ref, dict):
                    continue
                ref_content = ref.get("content") or ""
                chunks.append(
                    LightRAGChunk(
                        chunk_id=str(ref.get("reference_id", f"ref-{idx}")),
                        content=ref_content,
                        score=0.5,
                        file_id=ref.get("file_path"),
                    )
                )

        mode_str = (request.mode.value if request else "mix") if request else "mix"
        return LightRAGQueryResponse(
            query=(request.query if request else ""),
            mode=LightRAGQueryMode(mode_str),
            answer=llm_answer,
            chunks=chunks,
            total_tokens=int(raw.get("total_tokens", 0)),
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        return isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.ConnectError,
            ),
        )
