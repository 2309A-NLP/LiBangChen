from typing import Any

from pydantic import BaseModel, Field


"""
请求/响应数据模型定义模块。

包含查询请求、问答响应、会话消息、反馈、文档管理等
所有 API 端点使用的 Pydantic schema。
"""


class QueryRequest(BaseModel):
    """用户查询请求体。"""
    question: str = Field(min_length=1, description="用户问题")
    session_id: str | None = Field(default=None, description="会话标识")
    top_k: int | None = Field(default=None, ge=1, le=10)
    include_debug: bool = Field(default=False, description="是否返回调试信息")
    source_files: list[str] | None = Field(default=None, description="限定检索的文档列表")


class QueryUnderstandingResult(BaseModel):
    """查询理解结果，包含意图识别、消歧、子问题拆解等信息。"""
    intent: str
    normalized_question: str
    strategy: str = Field(default="rules", description="理解策略来源")
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ambiguous_terms: list[str] = Field(default_factory=list)
    clarification_needed: bool = Field(default=False, description="是否需要先追问澄清")
    clarification_question: str | None = Field(default=None, description="澄清追问")
    sub_questions: list[str] = Field(default_factory=list)
    abstracted_goal: str
    assumptions: list[str] = Field(default_factory=list)
    retrieval_hints: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """引用来源，标记回答中引用的具体文档片段。"""
    chunk_id: str
    source_id: str
    page_number: int | None = None
    score: float
    snippet: str


class QueryResponse(BaseModel):
    """问答响应，包含回答文本、引用列表和理解结果。"""
    answer_id: str
    session_id: str
    question: str
    answer: str
    citations: list[Citation]
    understanding: QueryUnderstandingResult
    debug: dict[str, Any] | None = None


class SessionMessage(BaseModel):
    """单条会话消息（用户或助手）。"""
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionHistoryResponse(BaseModel):
    """会话历史响应。"""
    session_id: str
    messages: list[SessionMessage] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """用户反馈请求体，支持 1-5 分评分和评论。"""
    answer_id: str
    question: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class FeedbackResponse(BaseModel):
    """反馈提交成功响应。"""
    message: str
    feedback_id: str


class DocumentSelectionRequest(BaseModel):
    """文档选择请求，指定后续查询限定的文档列表。"""
    source_files: list[str] = Field(default_factory=list)


class DocumentSelectionResponse(BaseModel):
    """文档选择响应。"""
    selected_sources: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str
    environment: str
    llm_provider: str
    query_understanding_mode: str


class DocumentStatusResponse(BaseModel):
    """文档加载状态响应，包含文件列表、分块数和加载时间等。"""
    source_pdf_dir: str
    source_files: list[str] = Field(default_factory=list)
    selected_sources: list[str] = Field(default_factory=list)
    document_count: int
    document_loaded: bool
    chunk_count: int
    last_loaded_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
    ocr_enabled: bool = False
    ocr_available: bool = False


class DocumentUploadTaskResponse(BaseModel):
    """Document upload task creation response."""
    task_id: str
    status: str
    uploaded_files: list[str] = Field(default_factory=list)
    message: str


class DocumentTaskStatusResponse(BaseModel):
    """Document upload task status response."""
    task_id: str
    status: str
    uploaded_files: list[str] = Field(default_factory=list)
    processed_files: int = 0
    total_files: int = 0
    current_file: str | None = None
    current_step: str
    message: str
    error: str | None = None
    selected_sources: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


# ---- 知识库管理相关模型 ----

class DocumentListItem(BaseModel):
    """知识库中单个文档的摘要信息。"""
    source_id: str
    chunk_count: int
    page_range: str  # e.g. "1-42"
    text_preview: str  # first ~200 chars of first chunk


class DocumentListResponse(BaseModel):
    """知识库文档列表响应。"""
    documents: list[DocumentListItem] = Field(default_factory=list)
    total_chunks: int


class ChunkItem(BaseModel):
    """文档分块详情。"""
    chunk_id: str
    page_number: int | None = None
    text: str
    char_count: int


class DocumentChunksResponse(BaseModel):
    """指定文档的所有分块响应。"""
    source_id: str
    chunks: list[ChunkItem] = Field(default_factory=list)
    total_chunks: int


class DocumentDeleteResponse(BaseModel):
    """文档删除响应。"""
    message: str
    deleted_source: str
    remaining_chunks: int


class WarmupStatusResponse(BaseModel):
    """检索器预热状态响应。"""
    status: str
    message: str
    selected_only: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class OCRStatusResponse(BaseModel):
    """OCR capability status response."""
    enabled: bool
    available: bool
    engine: str
    message: str
