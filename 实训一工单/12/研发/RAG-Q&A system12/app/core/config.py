from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


"""
全局配置模块。

通过 pydantic-settings 从 .env 文件和环境变量加载所有应用配置，
包括 LLM、Embedding、Milvus、检索器、会话存储等参数。
"""


class LightRAGSettings(BaseModel):
    """LightRAG sidecar service settings."""

    base_url: str = "http://localhost:9621"
    api_key: str | None = None
    timeout: int = 300
    working_dir: str = "./data/lightrag"
    default_mode: str = "mix"
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.3, ge=0.0)
    chunk_size: int = Field(default=1200, ge=1)
    chunk_overlap: int = Field(default=100, ge=0)
    max_parallel_insert: int = Field(default=4, ge=1)
    insert_retry: int = Field(default=3, ge=1)
    embedding_model_path: str = "BAAI/bge-m3"
    entity_types: list[str] = Field(
        default_factory=lambda: [
            "公司",
            "子公司",
            "分公司",
            "参股公司",
            "合营企业",
            "合伙企业",
            "民办非企业单位",
            "自然人",
            "股东",
            "实际控制人",
            "一致行动人",
            "董事",
            "监事",
            "高级管理人员",
            "核心技术人才",
            "独立董事",
            "董事会秘书",
            "关联方",
            "客户",
            "供应商",
            "经销商",
            "服务商",
            "竞争对手",
            "战略合作伙伴",
            "产品",
            "服务",
            "商标",
            "专利",
            "核心技术",
            "软件著作权",
            "域名",
            "商业秘密",
            "财务指标",
            "募投项目",
            "资质许可",
            "重大合同",
            "担保事项",
            "法律诉讼",
            "行政处罚",
            "行业",
            "细分市场",
            "地区",
            "监管政策",
            "行业标准",
            "风险因素",
            "竞争风险",
            "政策风险",
            "技术风险",
        ]
    )
    relation_types: list[str] = Field(
        default_factory=lambda: [
            "持股",
            "控股",
            "被控股",
            "参股",
            "被参股",
            "控制",
            "被控制",
            "共同控制",
            "一致行动",
            "表决权委托",
            "任职",
            "曾任",
            "兼任",
            "采购自",
            "销售给",
            "代理",
            "经销",
            "投资",
            "被投资",
            "合作",
            "拥有专利",
            "拥有商标",
            "拥有著作权",
            "许可使用",
            "被许可使用",
            "授权",
            "被授权",
            "担保",
            "被担保",
            "质押",
            "诉讼原告",
            "诉讼被告",
            "被处罚",
            "被监管问询",
            "属于行业",
            "属于细分市场",
            "受政策影响",
            "关联交易",
            "关联担保",
            "关联资金往来",
        ]
    )


class Settings(BaseSettings):
    """应用全局配置，支持从环境变量和 .env 文件自动加载。"""
    app_name: str = Field(default="PDF Document Q&A System", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    source_pdf_dir: Path = Field(
        default=PROJECT_ROOT / "data/source",
        alias="SOURCE_PDF_DIR",
    )
    source_pdf_path: Path = Field(
        default=PROJECT_ROOT / "data/source/sample.pdf",
        alias="SOURCE_PDF_PATH",
    )
    feedback_store_path: Path = Field(
        default=PROJECT_ROOT / "data/processed/feedback.jsonl",
        alias="FEEDBACK_STORE_PATH",
    )
    document_cache_path: Path = Field(
        default=PROJECT_ROOT / "data/processed/document_cache.json",
        alias="DOCUMENT_CACHE_PATH",
    )
    pdf_parser_provider: str = Field(default="pypdf", alias="PDF_PARSER_PROVIDER")
    milvus_state_path: Path = Field(
        default=PROJECT_ROOT / "data/processed/milvus_state.json",
        alias="MILVUS_STATE_PATH",
    )
    default_top_k: int = Field(default=8, alias="DEFAULT_TOP_K")
    max_chunk_length: int = Field(default=4000, alias="MAX_CHUNK_LENGTH")
    table_chunk_length: int = Field(default=1800, alias="TABLE_CHUNK_LENGTH")
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    query_understanding_mode: str = Field(default="rules", alias="QUERY_UNDERSTANDING_MODE")
    query_understanding_api_key: str | None = Field(
        default=None,
        alias="QUERY_UNDERSTANDING_API_KEY",
    )
    query_understanding_base_url: str | None = Field(
        default=None,
        alias="QUERY_UNDERSTANDING_BASE_URL",
    )
    query_understanding_model: str | None = Field(
        default=None,
        alias="QUERY_UNDERSTANDING_MODEL",
    )
    query_understanding_timeout_seconds: float = Field(
        default=15.0,
        alias="QUERY_UNDERSTANDING_TIMEOUT_SECONDS",
    )
    query_understanding_temperature: float = Field(
        default=0.1,
        alias="QUERY_UNDERSTANDING_TEMPERATURE",
    )
    query_understanding_fallback_enabled: bool = Field(
        default=True,
        alias="QUERY_UNDERSTANDING_FALLBACK_ENABLED",
    )
    query_understanding_local_first_enabled: bool = Field(
        default=True,
        alias="QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED",
    )
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    session_store_backend: str = Field(default="memory", alias="SESSION_STORE_BACKEND")
    session_store_key_prefix: str = Field(default="rag:qna:session:", alias="SESSION_STORE_KEY_PREFIX")
    session_store_ttl_seconds: int = Field(default=86400, alias="SESSION_STORE_TTL_SECONDS")
    retriever_type: str = Field(default="hybrid", alias="RETRIEVER_TYPE")
    fulltext_default_operator: str = Field(default="smart", alias="FULLTEXT_DEFAULT_OPERATOR")
    fulltext_title_weight: float = Field(default=2.4, alias="FULLTEXT_TITLE_WEIGHT")
    fulltext_summary_weight: float = Field(default=1.4, alias="FULLTEXT_SUMMARY_WEIGHT")
    fulltext_body_weight: float = Field(default=1.0, alias="FULLTEXT_BODY_WEIGHT")
    fulltext_fuzzy_max_distance: int = Field(default=1, alias="FULLTEXT_FUZZY_MAX_DISTANCE")
    hybrid_text_retriever: str = Field(default="fulltext", alias="HYBRID_TEXT_RETRIEVER")
    hybrid_fusion_strategy: str = Field(default="rrf", alias="HYBRID_FUSION_STRATEGY")
    hybrid_fulltext_weight: float = Field(default=0.45, alias="HYBRID_FULLTEXT_WEIGHT")
    hybrid_vector_weight: float = Field(default=0.55, alias="HYBRID_VECTOR_WEIGHT")
    hybrid_candidate_multiplier: int = Field(default=5, alias="HYBRID_CANDIDATE_MULTIPLIER")
    hybrid_vote_min_agreement: int = Field(default=1, alias="HYBRID_VOTE_MIN_AGREEMENT")
    rrf_k: int = Field(default=60, alias="RRF_K")
    reranker_enabled: bool = Field(default=True, alias="RERANKER_ENABLED")
    reranker_types: str = Field(default="cross_encoder", alias="RERANKER_TYPES")
    reranker_model_path: str = Field(
        default=r"C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-reranker-base\bge-reranker-base\bge-reranker-base",
        alias="RERANKER_MODEL_PATH",
    )
    reranker_device: str = Field(default="cpu", alias="RERANKER_DEVICE")
    reranker_max_length: int = Field(default=512, alias="RERANKER_MAX_LENGTH")
    reranker_top_n: int = Field(default=8, alias="RERANKER_TOP_N")
    reranker_llm_api_key: str | None = Field(default=None, alias="RERANKER_LLM_API_KEY")
    reranker_llm_base_url: str | None = Field(default=None, alias="RERANKER_LLM_BASE_URL")
    reranker_llm_model: str | None = Field(default=None, alias="RERANKER_LLM_MODEL")
    reranker_llm_timeout_seconds: float = Field(
        default=15.0,
        alias="RERANKER_LLM_TIMEOUT_SECONDS",
    )
    reranker_feedback_positive_rating: int = Field(
        default=4,
        alias="RERANKER_FEEDBACK_POSITIVE_RATING",
    )
    embedding_provider: str = Field(default="sentence_transformers", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(
        default=r"C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-m3",
        alias="EMBEDDING_MODEL_NAME",
    )
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")
    milvus_host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_collection_name: str = Field(
        default="rag_qna_chunks",
        alias="MILVUS_COLLECTION_NAME",
    )
    milvus_index_type: str = Field(default="IVF_FLAT", alias="MILVUS_INDEX_TYPE")
    milvus_metric_type: str = Field(default="COSINE", alias="MILVUS_METRIC_TYPE")
    milvus_nlist: int = Field(default=1024, alias="MILVUS_NLIST")
    milvus_search_nprobe: int = Field(default=16, alias="MILVUS_SEARCH_NPROBE")
    lightrag_base_url: str = Field(default="http://localhost:9621", alias="LIGHTRAG_BASE_URL")
    lightrag_api_key: str | None = Field(default=None, alias="LIGHTRAG_API_KEY")
    lightrag_timeout: int = Field(default=300, alias="LIGHTRAG_TIMEOUT")
    lightrag_working_dir: str = Field(default="./data/lightrag", alias="LIGHTRAG_WORKING_DIR")
    lightrag_default_mode: str = Field(default="mix", alias="LIGHTRAG_DEFAULT_MODE")
    lightrag_top_k: int = Field(default=20, ge=1, le=100, alias="LIGHTRAG_TOP_K")
    lightrag_min_score: float = Field(default=0.3, ge=0.0, alias="LIGHTRAG_MIN_SCORE")
    lightrag_chunk_size: int = Field(default=1200, ge=1, alias="LIGHTRAG_CHUNK_SIZE")
    lightrag_chunk_overlap: int = Field(default=100, ge=0, alias="LIGHTRAG_CHUNK_OVERLAP")
    lightrag_max_parallel_insert: int = Field(default=4, ge=1, alias="LIGHTRAG_MAX_PARALLEL_INSERT")
    lightrag_insert_retry: int = Field(default=3, ge=1, alias="LIGHTRAG_INSERT_RETRY")
    lightrag_embedding_model_path: str = Field(
        default="BAAI/bge-m3",
        alias="LIGHTRAG_EMBEDDING_MODEL_PATH",
    )

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        self._normalize_paths()

    def model_post_init(self, __context: object) -> None:
        self._normalize_paths()

    def _normalize_paths(self) -> None:
        for field_name in (
            "source_pdf_dir",
            "source_pdf_path",
            "feedback_store_path",
            "document_cache_path",
            "milvus_state_path",
        ):
            path = getattr(self, field_name)
            if not path.is_absolute():
                setattr(self, field_name, PROJECT_ROOT / path)

    @property
    def lightrag(self) -> LightRAGSettings:
        return LightRAGSettings(
            base_url=self.lightrag_base_url,
            api_key=self.lightrag_api_key,
            timeout=self.lightrag_timeout,
            working_dir=self.lightrag_working_dir,
            default_mode=self.lightrag_default_mode,
            top_k=self.lightrag_top_k,
            min_score=self.lightrag_min_score,
            chunk_size=self.lightrag_chunk_size,
            chunk_overlap=self.lightrag_chunk_overlap,
            max_parallel_insert=self.lightrag_max_parallel_insert,
            insert_retry=self.lightrag_insert_retry,
            embedding_model_path=self.lightrag_embedding_model_path,
        )

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )
