"""Retriever factory."""

from app.core.config import Settings
from app.core.constants import LIGHTRAG_MODES, RetrievalMode
from app.services.document_ingestion import DocumentIngestionService
from app.services.embeddings import EmbeddingService
from app.services.retrievers.base import BaseRetriever
from app.services.retrievers.fulltext import FullTextRetriever
from app.services.retrievers.hybrid_rrf import HybridRetriever
from app.services.retrievers.keyword import KeywordRetriever
from app.services.retrievers.lightrag import LightRAGRetriever
from app.services.retrievers.milvus import MilvusRetriever


def build_retriever(
    settings: Settings,
    document_ingestion_service: DocumentIngestionService,
    retriever_type_override: str | None = None,
) -> BaseRetriever:
    """Build a retriever instance from global settings or a request override."""

    retriever_type = (retriever_type_override or settings.retriever_type).strip().lower()
    keyword_retriever = KeywordRetriever(document_ingestion_service)
    fulltext_retriever = FullTextRetriever(settings, document_ingestion_service)

    try:
        retrieval_mode = RetrievalMode(retriever_type)
    except ValueError:
        retrieval_mode = None

    if retrieval_mode in LIGHTRAG_MODES:
        return LightRAGRetriever(
            settings=settings.lightrag,
            document_ingestion_service=document_ingestion_service,
            retrieval_mode=retriever_type,
        )

    if retriever_type == RetrievalMode.KEYWORD.value:
        return keyword_retriever

    if retriever_type in {RetrievalMode.FULLTEXT.value, "text", "fts"}:
        return fulltext_retriever

    embedding_service = EmbeddingService(settings)
    milvus_retriever = MilvusRetriever(
        settings=settings,
        document_ingestion_service=document_ingestion_service,
        embedding_service=embedding_service,
    )

    if retriever_type in {"milvus", RetrievalMode.VECTOR.value}:
        return milvus_retriever

    if retriever_type in {
        RetrievalMode.HYBRID.value,
        "hybrid_rrf",
        "rrf",
        "hybrid_weighted",
        "hybrid_vote",
    }:
        text_retriever = (
            keyword_retriever
            if settings.hybrid_text_retriever.strip().lower() == "keyword"
            else fulltext_retriever
        )
        return HybridRetriever(
            settings=settings,
            text_retriever=text_retriever,
            vector_retriever=milvus_retriever,
            text_retriever_name=settings.hybrid_text_retriever.strip().lower() or "fulltext",
        )

    raise ValueError(f"Unsupported RETRIEVER_TYPE: {retriever_type}")
