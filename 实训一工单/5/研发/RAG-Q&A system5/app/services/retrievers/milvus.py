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
        self._collection: Any | None = None
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

        collection = self._get_collection()
        expr = self._build_source_filter()
        search_params = {
            "metric_type": self.settings.milvus_metric_type,
            "params": {"nprobe": self.settings.milvus_search_nprobe},
        }
        search_result = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id", "source_id", "page_number", "text"],
        )

        results: list[RetrievedChunk] = []
        for hits in search_result:
            for hit in hits:
                entity = hit.entity
                page_number = entity.get("page_number")
                results.append(
                    RetrievedChunk(
                        chunk=DocumentChunk(
                            chunk_id=str(entity.get("chunk_id")),
                            source_id=str(entity.get("source_id")),
                            page_number=None if page_number in (-1, None) else int(page_number),
                            text=str(entity.get("text")),
                        ),
                        score=round(float(hit.score), 4),
                    )
                )
        return results

    def _ensure_index(self, chunks: list[DocumentChunk]) -> None:
        import os

        with self._index_lock:
            collection = self._get_collection()
            signature = self._build_signature(chunks)
            force_rebuild = os.environ.get("HERMES_RAG_REBUILD_INDEX") == "1"

            if (
                not force_rebuild
                and self._indexed_signature == signature
                and collection.num_entities > 0
            ):
                return

            texts = [chunk.text for chunk in chunks]
            vectors = self.embedding_service.embed_documents(texts)
            if not vectors:
                return

            try:
                if collection.num_entities > 0:
                    collection.delete(expr="pk >= 0")
                    collection.flush()

                rows = [
                    list(range(len(chunks))),
                    [chunk.chunk_id for chunk in chunks],
                    [chunk.source_id for chunk in chunks],
                    [chunk.page_number if chunk.page_number is not None else -1 for chunk in chunks],
                    texts,
                    vectors,
                ]
                collection.insert(rows)
                collection.flush()
                collection.load()
                self._indexed_signature = signature
                self._save_cached_signature(signature)
            except Exception as exc:
                if not self._should_rebuild_collection(exc):
                    raise
                logger.warning(
                    "Milvus collection %s indexing failed due to stale state; rebuilding collection.",
                    self.settings.milvus_collection_name,
                )
                collection = self._rebuild_collection()
                rows = [
                    list(range(len(chunks))),
                    [chunk.chunk_id for chunk in chunks],
                    [chunk.source_id for chunk in chunks],
                    [chunk.page_number if chunk.page_number is not None else -1 for chunk in chunks],
                    texts,
                    vectors,
                ]
                collection.insert(rows)
                collection.flush()
                collection.load()
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

        from pymilvus import Collection, connections, utility

        connections.connect(
            alias="default",
            host=self.settings.milvus_host,
            port=self.settings.milvus_port,
        )

        collection_name = self.settings.milvus_collection_name
        if utility.has_collection(collection_name):
            collection = Collection(collection_name)
        else:
            collection = self._create_collection(collection_name)

        if not collection.indexes:
            collection.create_index(
                field_name="embedding",
                index_params={
                    "index_type": self.settings.milvus_index_type,
                    "metric_type": self.settings.milvus_metric_type,
                    "params": {"nlist": self.settings.milvus_nlist},
                },
            )

        self._collection = collection
        return collection

    def _rebuild_collection(self):
        from pymilvus import utility

        collection_name = self.settings.milvus_collection_name
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
        collection = self._create_collection(collection_name)
        collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": self.settings.milvus_index_type,
                "metric_type": self.settings.milvus_metric_type,
                "params": {"nlist": self.settings.milvus_nlist},
            },
        )
        self._collection = collection
        self._indexed_signature = None
        self._clear_cached_signature()
        return collection

    def _create_collection(self, collection_name: str):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema

        dimension = len(self.embedding_service.embed_query("测试向量维度"))
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=False),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="source_id", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="page_number", dtype=DataType.INT64),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
            ],
            description="RAG chunk vectors",
        )
        return Collection(name=collection_name, schema=schema)

    def _build_query_text(
        self,
        question: str,
        retrieval_hints: dict[str, object] | None,
    ) -> str:
        if not retrieval_hints:
            return question

        parts = [question]
        for key in ("keywords", "prefer_sections", "entities", "notes"):
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
