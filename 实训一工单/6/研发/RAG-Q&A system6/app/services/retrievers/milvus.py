from __future__ import annotations

"""基于 Milvus 向量数据库的检索器实现。

将文档片段嵌入为向量后存入 Milvus Collection，检索时通过 ANN 搜索
返回最相关的片段。支持增量索引、签名缓存和自动重建。
"""

import json
import logging
from hashlib import md5
from threading import Lock
from typing import Any

from app.core.config import Settings
from app.services.document_ingestion import DocumentChunk, DocumentIngestionService
from app.services.embeddings import EmbeddingService
from app.services.retrievers.base import BaseRetriever, RetrievedChunk


logger = logging.getLogger(__name__)


class MilvusRetriever(BaseRetriever):
    """基于 Milvus 向量数据库的检索器。

    使用 ``EmbeddingService`` 将文档片段和查询文本转换为向量，
    在 Milvus 中执行近似最近邻搜索。通过 MD5 签名判断索引是否需要更新。
    """
    def __init__(
        self,
        settings: Settings,
        document_ingestion_service: DocumentIngestionService,
        embedding_service: EmbeddingService,
    ) -> None:
        self.settings = settings
        self.document_ingestion_service = document_ingestion_service
        self.embedding_service = embedding_service
        self._client: Any | None = None
        self._collection: str | None = None
        self._indexed_signature: str | None = self._load_cached_signature()
        self._index_lock = Lock()

    def prepare(self, selected_only: bool = False) -> None:
        chunks = self._get_indexable_chunks(selected_only=selected_only)
        if not chunks:
            return
        self._ensure_index(chunks)

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        return self.retrieve_more(question=question, top_k=top_k, retrieval_hints=retrieval_hints)

    def retrieve_more(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        chunks = self._get_indexable_chunks(selected_only=False)
        if not chunks:
            return []

        self._ensure_index(chunks)
        query_text = self._build_query_text(question, retrieval_hints)
        query_vector = self.embedding_service.embed_query(query_text)
        if not query_vector:
            return []

        collection_name = self._get_collection()
        client = self._get_client()
        expr = self._build_source_filter()
        search_params = {
            "metric_type": self.settings.milvus_metric_type,
            "params": {"nprobe": self.settings.milvus_search_nprobe},
        }
        search_result = client.search(
            collection_name=collection_name,
            data=[query_vector],
            anns_field="embedding",
            search_params=search_params,
            limit=top_k,
            filter=expr or "",
            output_fields=["chunk_id", "source_id", "page_number", "text"],
        )

        results: list[RetrievedChunk] = []
        for hits in search_result:
            for hit in hits:
                entity = hit.get("entity")
                if not isinstance(entity, dict):
                    entity = hit
                page_number = entity.get("page_number")
                results.append(
                    RetrievedChunk(
                        chunk=DocumentChunk(
                            chunk_id=str(entity.get("chunk_id")),
                            source_id=str(entity.get("source_id")),
                            page_number=None if page_number in (-1, None) else int(page_number),
                            text=str(entity.get("text")),
                        ),
                        score=round(float(hit.get("distance", hit.get("score", 0.0))), 4),
                    )
                )
        return results

    def _ensure_index(self, chunks: list[DocumentChunk]) -> None:
        import os

        with self._index_lock:
            collection_name = self._get_collection()
            client = self._get_client()
            signature = self._build_signature(chunks)
            force_rebuild = os.environ.get("HERMES_RAG_REBUILD_INDEX") == "1"

            if (
                not force_rebuild
                and self._indexed_signature == signature
                and self._collection_entity_count(collection_name) > 0
            ):
                return

            texts = [chunk.text for chunk in chunks]
            vectors = self.embedding_service.embed_documents(texts)
            if not vectors:
                return

            rows = self._build_rows(chunks, texts, vectors)
            try:
                if self._collection_entity_count(collection_name) > 0:
                    client.delete(collection_name=collection_name, filter="pk >= 0")
                    client.flush(collection_name=collection_name)

                client.insert(collection_name=collection_name, data=rows)
                client.flush(collection_name=collection_name)
                client.load_collection(collection_name=collection_name)
                self._indexed_signature = signature
                self._save_cached_signature(signature)
            except Exception as exc:
                if not self._should_rebuild_collection(exc):
                    raise
                logger.warning(
                    "Milvus collection %s indexing failed due to stale state; rebuilding collection.",
                    self.settings.milvus_collection_name,
                )
                collection_name = self._rebuild_collection()
                client.insert(collection_name=collection_name, data=rows)
                client.flush(collection_name=collection_name)
                client.load_collection(collection_name=collection_name)
                self._indexed_signature = signature
                self._save_cached_signature(signature)

    def _get_indexable_chunks(self, selected_only: bool) -> list[DocumentChunk]:
        selected_sources = self.document_ingestion_service.status().get("selected_sources", [])
        has_selection = isinstance(selected_sources, list) and bool(selected_sources)
        if selected_only:
            return self.document_ingestion_service.chunks() if has_selection else []
        if has_selection:
            return self.document_ingestion_service.chunks()
        return self.document_ingestion_service.all_chunks()

    def _get_collection(self):
        if self._collection is not None:
            return self._collection

        client = self._get_client()
        collection_name = self.settings.milvus_collection_name
        if not client.has_collection(collection_name):
            self._create_collection(collection_name)

        if not client.list_indexes(collection_name=collection_name):
            self._create_vector_index(collection_name)

        client.load_collection(collection_name=collection_name)
        self._collection = collection_name
        return collection_name

    def _rebuild_collection(self):
        client = self._get_client()
        collection_name = self.settings.milvus_collection_name
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)
        self._create_collection(collection_name)
        self._create_vector_index(collection_name)
        client.load_collection(collection_name=collection_name)
        self._collection = collection_name
        self._indexed_signature = None
        self._clear_cached_signature()
        return collection_name

    def _create_collection(self, collection_name: str):
        from pymilvus import DataType, MilvusClient

        dimension = len(self.embedding_service.embed_query("测试向量维度"))
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=255)
        schema.add_field("source_id", DataType.VARCHAR, max_length=255)
        schema.add_field("page_number", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
        self._get_client().create_collection(collection_name=collection_name, schema=schema)
        return collection_name

    def _create_vector_index(self, collection_name: str) -> None:
        from pymilvus import MilvusClient

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type=self.settings.milvus_index_type,
            metric_type=self.settings.milvus_metric_type,
            params={"nlist": self.settings.milvus_nlist},
        )
        self._get_client().create_index(collection_name=collection_name, index_params=index_params)

    def _get_client(self):
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(
                uri=f"http://{self.settings.milvus_host}:{self.settings.milvus_port}"
            )
        return self._client

    def _collection_entity_count(self, collection_name: str) -> int:
        stats = self._get_client().get_collection_stats(collection_name=collection_name)
        raw_count = stats.get("row_count", 0)
        try:
            return int(raw_count)
        except (TypeError, ValueError):
            return 0

    def _build_rows(
        self,
        chunks: list[DocumentChunk],
        texts: list[str],
        vectors: list[list[float]],
    ) -> list[dict[str, object]]:
        return [
            {
                "pk": index,
                "chunk_id": chunk.chunk_id,
                "source_id": chunk.source_id,
                "page_number": chunk.page_number if chunk.page_number is not None else -1,
                "text": text,
                "embedding": vector,
            }
            for index, (chunk, text, vector) in enumerate(zip(chunks, texts, vectors))
        ]

    def _build_query_text(
        self,
        question: str,
        retrieval_hints: dict[str, object] | None,
    ) -> str:
        if not retrieval_hints:
            return question

        parts = [question]
        # 优先使用抽象目标（包含回答意图），对语义搜索更有效
        abstracted_goal = retrieval_hints.get("abstracted_goal")
        if isinstance(abstracted_goal, str) and abstracted_goal.strip():
            parts.append(abstracted_goal.strip())

        for key in ("keywords", "entities", "prefer_sections", "notes"):
            value = retrieval_hints.get(key)
            if isinstance(value, list):
                parts.extend(item for item in value if isinstance(item, str) and item.strip())
        return " ".join(parts)

    def _build_source_filter(self) -> str | None:
        selected_sources = self.document_ingestion_service.status().get("selected_sources", [])
        if not isinstance(selected_sources, list) or not selected_sources:
            return None
        escaped = [source.replace("\\", "\\\\").replace('"', '\\"') for source in selected_sources]
        joined = ", ".join(f'"{item}"' for item in escaped)
        return f"source_id in [{joined}]"

    def _build_signature(self, chunks: list[DocumentChunk]) -> str:
        digest = md5()
        for chunk in chunks:
            digest.update(chunk.chunk_id.encode("utf-8"))
            digest.update(chunk.source_id.encode("utf-8"))
            digest.update(str(chunk.page_number).encode("utf-8"))
            digest.update(chunk.text.encode("utf-8"))
        return digest.hexdigest()

    def _should_rebuild_collection(self, exc: Exception) -> bool:
        message = str(exc).lower()
        rebuild_markers = (
            "invalid local path",
            "collection not loaded",
            "cannot find",
        )
        return any(marker in message for marker in rebuild_markers)

    def _load_cached_signature(self) -> str | None:
        state_path = self.settings.milvus_state_path
        if not state_path.exists():
            return None
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        signature = payload.get("indexed_signature")
        if not isinstance(signature, str) or not signature.strip():
            return None
        return signature

    def _save_cached_signature(self, signature: str) -> None:
        state_path = self.settings.milvus_state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collection_name": self.settings.milvus_collection_name,
            "indexed_signature": signature,
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_cached_signature(self) -> None:
        state_path = self.settings.milvus_state_path
        if state_path.exists():
            try:
                state_path.unlink()
            except OSError:
                logger.warning("Failed to delete stale Milvus state file: %s", state_path)
