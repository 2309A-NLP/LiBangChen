import logging
from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService
from app.services.feedback import FeedbackService
from app.services.ingestion_status import IngestionStatusService
from app.services.llm.factory import build_llm_client
from app.services.pipeline import QAPipelineService
from app.services.query_understanding import QueryUnderstandingService
from app.services.reranker import (
    CrossEncoderReranker,
    FeedbackAdaptiveReranker,
    LLMReranker,
    RerankerService,
    TFIDFReranker,
)
from app.services.retrieval_generation import RetrievalGenerationService
from app.services.retrievers.factory import build_retriever
from app.services.session_service import SessionService
from app.services.session_store import InMemorySessionStore, RedisSessionStore
from app.services.warmup_status import WarmupStatusService


"""
依赖注入容器模块。

集中创建和管理所有服务实例，替代手动的依赖注入，
确保各服务间的依赖关系清晰可控。
"""

logger = logging.getLogger(__name__)


class AppContainer:
    """应用依赖容器，负责统一构建和持有各服务实例。"""
    def __init__(
        self,
        settings: Settings,
        document_ingestion_service: DocumentIngestionService,
        query_understanding_service: QueryUnderstandingService,
        retrieval_generation_service: RetrievalGenerationService,
        feedback_service: FeedbackService,
        pipeline_service: QAPipelineService,
        session_service: SessionService,
        ingestion_status_service: IngestionStatusService,
        warmup_status_service: WarmupStatusService,
    ) -> None:
        self.settings = settings
        self.document_ingestion_service = document_ingestion_service
        self.query_understanding_service = query_understanding_service
        self.retrieval_generation_service = retrieval_generation_service
        self.feedback_service = feedback_service
        self.pipeline_service = pipeline_service
        self.session_service = session_service
        self.ingestion_status_service = ingestion_status_service
        self.warmup_status_service = warmup_status_service
        self.available_rerankers: dict[str, object] = {}

    def prepare_retrieval(self, selected_only: bool = False) -> None:
        self.retrieval_generation_service.prepare_retrieval(selected_only=selected_only)

    @classmethod
    def build(cls) -> "AppContainer":
        """工厂方法：根据配置构建完整的依赖图，返回容器实例。"""
        settings = Settings()
        document_ingestion_service = DocumentIngestionService(settings)
        retriever = build_retriever(settings, document_ingestion_service)
        llm_client = build_llm_client(settings)
        reranker = cls._build_reranker(settings)
        query_understanding_service = QueryUnderstandingService(settings)
        retrieval_generation_service = RetrievalGenerationService(
            retriever=retriever,
            llm_client=llm_client,
            default_top_k=settings.default_top_k,
            reranker=reranker,
            settings=settings,
            document_ingestion_service=document_ingestion_service,
        )
        feedback_service = FeedbackService(settings.feedback_store_path)
        session_service = SessionService(cls._build_session_store(settings))
        ingestion_status_service = IngestionStatusService()
        warmup_status_service = WarmupStatusService()
        pipeline_service = QAPipelineService(
            query_understanding_service=query_understanding_service,
            retrieval_generation_service=retrieval_generation_service,
            session_service=session_service,
        )
        container = cls(
            settings=settings,
            document_ingestion_service=document_ingestion_service,
            query_understanding_service=query_understanding_service,
            retrieval_generation_service=retrieval_generation_service,
            feedback_service=feedback_service,
            pipeline_service=pipeline_service,
            session_service=session_service,
            ingestion_status_service=ingestion_status_service,
            warmup_status_service=warmup_status_service,
        )
        container.available_rerankers = cls.build_reranker_catalog(settings)
        retrieval_generation_service.set_available_rerankers(container.available_rerankers)
        return container

    @staticmethod
    def _build_reranker(settings: Settings) -> RerankerService | None:
        """构建重排序服务，初始化失败时优雅降级返回 None。"""
        if not settings.reranker_enabled:
            return None
        try:
            strategy_names = [
                item.strip().lower()
                for item in settings.reranker_types.split(",")
                if item.strip()
            ]
            if not strategy_names:
                strategy_names = ["cross_encoder"]

            rerankers = []
            for name in strategy_names:
                if name in {"cross_encoder", "cross-encoder", "ce"}:
                    rerankers.append(
                        CrossEncoderReranker(
                            model_path=settings.reranker_model_path,
                            device=settings.reranker_device,
                            max_length=settings.reranker_max_length,
                            top_n=settings.reranker_top_n,
                        )
                    )
                    continue
                if name == "tfidf":
                    rerankers.append(TFIDFReranker())
                    continue
                if name == "feedback":
                    rerankers.append(
                        FeedbackAdaptiveReranker(
                            store_path=settings.feedback_store_path,
                            positive_rating_threshold=settings.reranker_feedback_positive_rating,
                        )
                    )
                    continue
                if name == "llm":
                    rerankers.append(
                        LLMReranker(
                            api_key=settings.reranker_llm_api_key or settings.llm_api_key,
                            base_url=settings.reranker_llm_base_url or settings.llm_base_url,
                            model=settings.reranker_llm_model or settings.llm_model,
                            timeout_seconds=settings.reranker_llm_timeout_seconds,
                        )
                    )
                    continue
                raise ValueError(f"Unsupported reranker type: {name}")
            return RerankerService(rerankers=rerankers, top_n=settings.reranker_top_n)
        except Exception:
            logger.warning("Failed to initialize reranker, disabling.", exc_info=True)
            return None

    @staticmethod
    def build_reranker_catalog(settings: Settings) -> dict[str, object]:
        catalog: dict[str, object] = {}
        try:
            catalog["cross_encoder"] = CrossEncoderReranker(
                model_path=settings.reranker_model_path,
                device=settings.reranker_device,
                max_length=settings.reranker_max_length,
                top_n=settings.reranker_top_n,
            )
        except Exception:
            logger.warning("Failed to initialize cross_encoder reranker in catalog.", exc_info=True)
        catalog["tfidf"] = TFIDFReranker()
        catalog["feedback"] = FeedbackAdaptiveReranker(
            store_path=settings.feedback_store_path,
            positive_rating_threshold=settings.reranker_feedback_positive_rating,
        )
        catalog["llm"] = LLMReranker(
            api_key=settings.reranker_llm_api_key or settings.llm_api_key,
            base_url=settings.reranker_llm_base_url or settings.llm_base_url,
            model=settings.reranker_llm_model or settings.llm_model,
            timeout_seconds=settings.reranker_llm_timeout_seconds,
        )
        return catalog

    @staticmethod
    def _build_session_store(settings: Settings):
        """根据配置选择会话存储后端（Redis 或内存），Redis 不可用时回退到内存存储。"""
        backend = settings.session_store_backend.strip().lower()
        if backend == "redis" and settings.redis_url:
            try:
                store = RedisSessionStore(
                    redis_url=settings.redis_url,
                    key_prefix=settings.session_store_key_prefix,
                    ttl_seconds=settings.session_store_ttl_seconds,
                )
                store.ping()
                return store
            except Exception:
                return InMemorySessionStore()
        return InMemorySessionStore()
