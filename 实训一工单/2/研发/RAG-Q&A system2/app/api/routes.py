import json
import logging
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.container import AppContainer
from app.schemas.query import (
    ChunkItem,
    DocumentChunksResponse,
    DocumentDeleteResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentSelectionRequest,
    DocumentSelectionResponse,
    DocumentStatusResponse,
    DocumentTaskStatusResponse,
    DocumentUploadTaskResponse,
    OCRStatusResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SessionHistoryResponse,
    WarmupStatusResponse,
)


"""
API 路由模块。

定义所有 REST 接口，包括健康检查、文档管理、查询问答、
会话历史、SSE 流式响应和用户反馈等端点。
"""

router = APIRouter(prefix="/api", tags=["qna"])
logger = logging.getLogger(__name__)


def get_container(request: Request) -> AppContainer:
    """FastAPI 依赖函数：从请求中获取应用依赖容器。"""
    return request.app.state.container


def start_background_prepare(container: AppContainer, *, selected_only: bool) -> None:
    """后台启动检索器预热，并通过 WarmupStatusService 跟踪预热进度。"""
    def runner() -> None:
        mode_message = "selected_documents" if selected_only else "all_documents"
        container.warmup_status_service.start(
            selected_only=selected_only,
            message=mode_message,
        )
        try:
            container.prepare_retrieval(selected_only=selected_only)
            container.warmup_status_service.succeed("ready")
        except Exception:
            container.warmup_status_service.fail(
                "warmup_failed",
                "Retriever warmup failed in background.",
            )
            logger.warning("Retriever warmup failed in background.", exc_info=True)

    Thread(target=runner, daemon=True).start()


def start_background_upload_task(
    container: AppContainer,
    *,
    task_id: str,
    saved_names: list[str],
) -> None:
    """Parse uploaded files in the background and track task progress."""

    def runner() -> None:
        task_service = container.document_task_service
        task_service.start(
            task_id,
            total_files=len(saved_names),
            message="Upload received. Preparing parsing task.",
        )
        try:
            for index, saved_name in enumerate(saved_names, start=1):
                task_service.update(
                    task_id,
                    processed_files=index - 1,
                    total_files=len(saved_names),
                    current_file=saved_name,
                    current_step="parsing",
                    message=f"Parsing {saved_name} ({index}/{len(saved_names)}).",
                )

            task_service.update(
                task_id,
                processed_files=0,
                total_files=len(saved_names),
                current_file=None,
                current_step="indexing",
                message="Rebuilding chunks and retrieval index.",
            )
            container.document_ingestion_service.load_document(force=True)
            container.document_ingestion_service.select_sources(saved_names)

            status = container.document_ingestion_service.status()
            task_service.update(
                task_id,
                processed_files=len(saved_names),
                total_files=len(saved_names),
                current_file=None,
                current_step="warmup",
                message="Warming up retriever for uploaded documents.",
                warnings=status.get("warnings", []),
            )
            start_background_prepare(container, selected_only=True)

            task_service.succeed(
                task_id,
                processed_files=len(saved_names),
                total_files=len(saved_names),
                current_step="completed",
                message="Upload parsing completed.",
                selected_sources=status["selected_sources"],
                chunk_count=status["chunk_count"],
                warnings=status["warnings"],
            )
        except Exception as exc:
            task_service.fail(
                task_id,
                current_step="failed",
                message="Upload parsing failed.",
                error=str(exc),
            )
            logger.warning("Background upload task failed.", exc_info=True)

    Thread(target=runner, daemon=True).start()


@router.get("/health", response_model=HealthResponse)
async def health(container: AppContainer = Depends(get_container)) -> HealthResponse:
    """健康检查接口：返回服务状态、运行环境和 LLM 配置信息。"""
    return HealthResponse(
        status="ok",
        environment=container.settings.app_env,
        llm_provider=container.settings.llm_provider,
        query_understanding_mode=container.settings.query_understanding_mode,
    )


@router.get("/document/status", response_model=DocumentStatusResponse)
async def document_status(
    container: AppContainer = Depends(get_container),
) -> DocumentStatusResponse:
    """查询当前文档加载状态（已加载文件数、分块数等）。"""
    status = container.document_ingestion_service.status()
    return DocumentStatusResponse(**status)


@router.get("/document/warmup", response_model=WarmupStatusResponse)
async def document_warmup_status(
    container: AppContainer = Depends(get_container),
) -> WarmupStatusResponse:
    """查询检索器预热状态（等待中/运行中/完成/失败）。"""
    return WarmupStatusResponse(**container.warmup_status_service.snapshot())


@router.get("/document/ocr/status", response_model=OCRStatusResponse)
async def document_ocr_status(
    container: AppContainer = Depends(get_container),
) -> OCRStatusResponse:
    """查询 OCR 能力状态。"""
    status = container.document_ingestion_service.ocr_service.status()
    return OCRStatusResponse(
        enabled=status.enabled,
        available=status.available,
        engine=status.engine,
        message=status.message,
    )


@router.post("/document/reload", response_model=DocumentStatusResponse)
async def reload_document(
    container: AppContainer = Depends(get_container),
) -> DocumentStatusResponse:
    """强制重新加载全部文档并触发后台预热。"""
    container.document_ingestion_service.load_document(force=True)
    start_background_prepare(container, selected_only=True)
    status = container.document_ingestion_service.status()
    return DocumentStatusResponse(**status)


@router.post("/document/select", response_model=DocumentSelectionResponse)
async def select_documents(
    payload: DocumentSelectionRequest,
    container: AppContainer = Depends(get_container),
) -> DocumentSelectionResponse:
    """设置当前检索范围，限定后续查询只从指定文档中检索。"""
    container.document_ingestion_service.select_sources(payload.source_files)
    status = container.document_ingestion_service.status()
    return DocumentSelectionResponse(selected_sources=status["selected_sources"])


@router.post("/document/upload", response_model=DocumentUploadTaskResponse)
async def upload_document(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> DocumentUploadTaskResponse:
    """上传一个或多个 PDF 文件，并在后台解析。"""
    form = await request.form()
    upload_files: list[UploadFile] = []
    for key in ("files", "file"):
        for item in form.getlist(key):
            if hasattr(item, "filename") and hasattr(item, "read"):
                upload_files.append(item)

    if not upload_files:
        raise HTTPException(status_code=400, detail="No PDF files were uploaded.")

    saved_names: list[str] = []
    for upload in upload_files:
        content = await upload.read()
        saved_name = container.document_ingestion_service.save_uploaded_pdf(
            upload.filename,
            content,
        )
        saved_names.append(saved_name)

    task = container.document_task_service.create_task(saved_names)
    start_background_upload_task(container, task_id=task["task_id"], saved_names=saved_names)
    return DocumentUploadTaskResponse(**task)


@router.get("/document/tasks/{task_id}", response_model=DocumentTaskStatusResponse)
async def document_task_status(
    task_id: str,
    container: AppContainer = Depends(get_container),
) -> DocumentTaskStatusResponse:
    """查询上传解析任务状态。"""
    try:
        task = container.document_task_service.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from None
    return DocumentTaskStatusResponse(**task)


@router.get("/kb/documents", response_model=DocumentListResponse)
async def list_kb_documents(
    container: AppContainer = Depends(get_container),
) -> DocumentListResponse:
    """列出知识库中所有已加载文档及其分块数量。"""
    docs = container.document_ingestion_service.list_documents()
    items = [DocumentListItem(**doc) for doc in docs]
    total = sum(item.chunk_count for item in items)
    return DocumentListResponse(documents=items, total_chunks=total)


@router.get("/kb/documents/{source_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    source_id: str,
    container: AppContainer = Depends(get_container),
) -> DocumentChunksResponse:
    """获取指定文档的所有分块详情。"""
    try:
        chunks = container.document_ingestion_service.get_document_chunks(source_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Document not found: {source_id}") from None
    items = [ChunkItem(**chunk) for chunk in chunks]
    return DocumentChunksResponse(source_id=source_id, chunks=items, total_chunks=len(items))


@router.delete("/kb/documents/{source_id}", response_model=DocumentDeleteResponse)
async def delete_kb_document(
    source_id: str,
    container: AppContainer = Depends(get_container),
) -> DocumentDeleteResponse:
    """删除指定文档并重新加载剩余文档。"""
    deleted = container.document_ingestion_service.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document not found: {source_id}")
    container.document_ingestion_service.load_document(force=True)
    start_background_prepare(container, selected_only=True)
    status = container.document_ingestion_service.status()
    return DocumentDeleteResponse(
        message=f"Document deleted: {source_id}",
        deleted_source=source_id,
        remaining_chunks=status["chunk_count"],
    )


@router.get("/session/{session_id}", response_model=SessionHistoryResponse)
async def session_history(
    session_id: str,
    container: AppContainer = Depends(get_container),
) -> SessionHistoryResponse:
    """获取指定会话的完整对话历史。"""
    return SessionHistoryResponse(
        session_id=session_id,
        messages=container.session_service.get_history(session_id),
    )


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    container: AppContainer = Depends(get_container),
) -> QueryResponse:
    """同步问答接口：理解问题、检索文档、生成回答并返回。"""
    container.document_ingestion_service.select_sources(payload.source_files)
    return container.pipeline_service.answer_question(payload)


@router.post("/query/stream")
async def query_stream(
    payload: QueryRequest,
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    """SSE 流式问答接口：通过 Server-Sent Events 逐步推送状态和结果。"""
    container.document_ingestion_service.select_sources(payload.source_files)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'status', 'message': 'processing'}, ensure_ascii=False)}\n\n"
        try:
            response = container.pipeline_service.answer_question(payload)
            yield f"data: {json.dumps({'type': 'result', 'payload': response.model_dump()}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest,
    container: AppContainer = Depends(get_container),
) -> FeedbackResponse:
    """提交用户对回答的反馈（评分和评论）。"""
    record = container.feedback_service.save_feedback(payload)
    return FeedbackResponse(message="Feedback saved", feedback_id=record["feedback_id"])
