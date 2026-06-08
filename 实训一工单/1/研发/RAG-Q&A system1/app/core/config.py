from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


"""
全局配置模块。

通过 pydantic-settings 从 .env 文件和环境变量加载所有应用配置，
包括 LLM、Embedding、Milvus、检索器、会话存储等参数。
"""


class Settings(BaseSettings):
    """应用全局配置，支持从环境变量和 .env 文件自动加载。"""
    app_name: str = Field(default="PDF Document Q&A System", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    source_pdf_dir: Path = Field(
        default=Path("data/source"),
        alias="SOURCE_PDF_DIR",
    )
    source_pdf_path: Path = Field(
        default=Path("data/source/sample.pdf"),
        alias="SOURCE_PDF_PATH",
    )
    feedback_store_path: Path = Field(
        default=Path("data/processed/feedback.jsonl"),
        alias="FEEDBACK_STORE_PATH",
    )
    milvus_state_path: Path = Field(
        default=Path("data/processed/milvus_state.json"),
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
    retriever_type: str = Field(default="hybrid_rrf", alias="RETRIEVER_TYPE")
    rrf_k: int = Field(default=60, alias="RRF_K")
    reranker_enabled: bool = Field(default=True, alias="RERANKER_ENABLED")
    reranker_model_path: str = Field(
        default=r"C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-reranker-base\bge-reranker-base\bge-reranker-base",
        alias="RERANKER_MODEL_PATH",
    )
    reranker_device: str = Field(default="cpu", alias="RERANKER_DEVICE")
    reranker_max_length: int = Field(default=512, alias="RERANKER_MAX_LENGTH")
    reranker_top_n: int = Field(default=8, alias="RERANKER_TOP_N")
    embedding_provider: str = Field(default="sentence_transformers", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(
        default=r"E:\Role_playing system\Role_playing system\models\bge-m3",
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )
