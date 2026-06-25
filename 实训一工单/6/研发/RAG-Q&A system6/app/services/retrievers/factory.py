"""检索器工厂模块。"""
from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService
from app.services.embeddings import EmbeddingService
from app.services.retrievers.base import BaseRetriever
from app.services.retrievers.fulltext import FullTextRetriever
from app.services.retrievers.hybrid_rrf import HybridRetriever
from app.services.retrievers.keyword import KeywordRetriever
from app.services.retrievers.milvus import MilvusRetriever


def build_retriever(
    settings: Settings,
    document_ingestion_service: DocumentIngestionService,
    retriever_type_override: str | None = None,
) -> BaseRetriever:
    """根据全局配置构建并返回检索器实例。"""
    retriever_type = (retriever_type_override or settings.retriever_type).strip().lower()
    keyword_retriever = KeywordRetriever(document_ingestion_service)
    fulltext_retriever = FullTextRetriever(settings, document_ingestion_service)

    if retriever_type == "keyword":
        return keyword_retriever

    if retriever_type in {"fulltext", "text", "fts"}:
        return fulltext_retriever

    embedding_service = EmbeddingService(settings)
    milvus_retriever = MilvusRetriever(
        settings=settings,
        document_ingestion_service=document_ingestion_service,
        embedding_service=embedding_service,
    )

    if retriever_type in {"milvus", "vector"}:
        return milvus_retriever

    if retriever_type in {"hybrid", "hybrid_rrf", "rrf", "hybrid_weighted", "hybrid_vote"}:
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

    raise ValueError(f"Unsupported RETRIEVER_TYPE: {settings.retriever_type}")
