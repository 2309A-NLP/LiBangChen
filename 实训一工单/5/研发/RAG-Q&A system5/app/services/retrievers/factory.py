"""检索器工厂模块。

根据配置项 ``RETRIEVER_TYPE`` 创建对应的检索器实例。
支持 ``keyword``（纯关键词）、``milvus``（纯向量）和 ``hybrid_rrf``
（关键词 + 向量 RRF 融合）三种模式。
"""
from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService
from app.services.embeddings import EmbeddingService
from app.services.retrievers.base import BaseRetriever
from app.services.retrievers.hybrid_rrf import HybridRRFRetriever
from app.services.retrievers.keyword import KeywordRetriever
from app.services.retrievers.milvus import MilvusRetriever


def build_retriever(
    settings: Settings,
    document_ingestion_service: DocumentIngestionService,
) -> BaseRetriever:
    """根据全局配置构建并返回检索器实例。"""
    retriever_type = settings.retriever_type.strip().lower()
    keyword_retriever = KeywordRetriever(document_ingestion_service)

    if retriever_type == "keyword":
        return keyword_retriever

    embedding_service = EmbeddingService(settings)
    milvus_retriever = MilvusRetriever(
        settings=settings,
        document_ingestion_service=document_ingestion_service,
        embedding_service=embedding_service,
    )

    if retriever_type == "milvus":
        return milvus_retriever

    if retriever_type in {"hybrid", "hybrid_rrf", "rrf"}:
        return HybridRRFRetriever(
            settings=settings,
            keyword_retriever=keyword_retriever,
            vector_retriever=milvus_retriever,
        )

    raise ValueError(f"Unsupported RETRIEVER_TYPE: {settings.retriever_type}")
