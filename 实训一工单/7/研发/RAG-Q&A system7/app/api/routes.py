import json
import inspect
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
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SessionHistoryResponse,
    WarmupStatusResponse,
)


router = APIRouter(prefix="/api", tags=["qna"])
logger = logging.getLogger(__name__)


def _format_stream_error(exc: Exception) -> str:
    message = str(exc)
    normalized = message.lower()
    if "fail connecting to server on 127.0.0.1:19530" in normalized or (
        "illegal connection params or server unavailable" in normalized
        and "19530" in normalized
    ):
        return "Milvus 未启动或不可用，请先启动 Milvus，或将检索模式切换为关键词检索 / 全文检索。"
    return message


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def _document_status_payload(container: AppContainer) -> dict[str, object]:
    status = container.document_ingestion_service.status()
    processing = container.ingestion_status_service.snapshot()
    processing_status = processing.get("status", "idle")
    processing_sources = processing.get("source_files", [])
    if (
        processing_status == "ready"
        and not status.get("document_count")
        and isinstance(processing_sources, list)
        and processing_sources
    ):
        try:
            container.document_ingestion_service.load_document(
                force=True,
                source_files=processing_sources,
            )
            status = container.document_ingestion_service.status()
            if not status.get("document_count"):
                container.document_ingestion_service.load_document(force=True)
                status = container.document_ingestion_service.status()
            container.document_ingestion_service.select_sources(processing_sources)
            status = container.document_ingestion_service.status()
        except Exception:
            logger.warning("Document status recovery reload failed.", exc_info=True)
    status.update(
        {
            "processing_status": processing_status,
            "processing_message": processing.get("message", "not_started"),
            "processing_sources": processing_sources,
            "processing_started_at": processing.get("started_at"),
            "processing_finished_at": processing.get("finished_at"),
            "processing_error": processing.get("error"),
        }
    )
    return status


def start_background_prepare(container: AppContainer, *, selected_only: bool) -> None:
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


def start_background_document_refresh(
    container: AppContainer,
    *,
    selected_sources: list[str] | None,
    message: str,
) -> None:
    source_files = list(selected_sources or [])
    container.ingestion_status_service.start(
        message=message,
        source_files=source_files,
    )

    def runner() -> None:
        try:
            load_kwargs = {"force": True}
            load_signature = inspect.signature(container.document_ingestion_service.load_document)
            if "source_files" in load_signature.parameters:
                load_kwargs["source_files"] = source_files or None
            container.document_ingestion_service.load_document(**load_kwargs)
            container.document_ingestion_service.select_sources(source_files)
            container.ingestion_status_service.succeed(
                "documents_ready",
                source_files=container.document_ingestion_service.status().get("selected_sources", []),
            )
            start_background_prepare(container, selected_only=True)
        except Exception as exc:
            container.ingestion_status_service.fail(
                "documents_failed",
                str(exc),
                source_files=source_files,
            )
            logger.warning("Document refresh failed in background.", exc_info=True)

    Thread(target=runner, daemon=True).start()


@router.get("/health", response_model=HealthResponse)
async def health(container: AppContainer = Depends(get_container)) -> HealthResponse:
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
    return DocumentStatusResponse(**_document_status_payload(container))


@router.get("/document/warmup", response_model=WarmupStatusResponse)
async def document_warmup_status(
    container: AppContainer = Depends(get_container),
) -> WarmupStatusResponse:
    return WarmupStatusResponse(**container.warmup_status_service.snapshot())


@router.post("/document/reload", response_model=DocumentStatusResponse)
async def reload_document(
    container: AppContainer = Depends(get_container),
) -> DocumentStatusResponse:
    selected_sources = container.document_ingestion_service.status().get("selected_sources", [])
    start_background_document_refresh(
        container,
        selected_sources=selected_sources if isinstance(selected_sources, list) else [],
        message="reload_requested",
    )
    return DocumentStatusResponse(**_document_status_payload(container))


@router.post("/document/select", response_model=DocumentSelectionResponse)
async def select_documents(
    payload: DocumentSelectionRequest,
    container: AppContainer = Depends(get_container),
) -> DocumentSelectionResponse:
    container.document_ingestion_service.select_sources(payload.source_files)
    status = container.document_ingestion_service.status()
    return DocumentSelectionResponse(selected_sources=status["selected_sources"])


@router.post("/document/upload", response_model=DocumentStatusResponse)
async def upload_document(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> DocumentStatusResponse:
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

    # 合并已有的选中文件，避免新文件覆盖旧文件
    existing_sources = container.document_ingestion_service.status().get("selected_sources", [])
    all_sources = list({*existing_sources, *saved_names})
    container.document_ingestion_service.select_sources(all_sources)
    start_background_document_refresh(
        container,
        selected_sources=all_sources,
        message="upload_received",
    )
    return DocumentStatusResponse(**_document_status_payload(container))


@router.get("/kb/documents", response_model=DocumentListResponse)
async def list_kb_documents(
    container: AppContainer = Depends(get_container),
) -> DocumentListResponse:
    docs = container.document_ingestion_service.list_documents()
    items = [DocumentListItem(**doc) for doc in docs]
    total = sum(item.chunk_count for item in items)
    return DocumentListResponse(documents=items, total_chunks=total)


@router.get("/kb/documents/{source_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    source_id: str,
    container: AppContainer = Depends(get_container),
) -> DocumentChunksResponse:
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
    deleted = container.document_ingestion_service.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document not found: {source_id}")
    container.document_ingestion_service.load_document(force=True)
    start_background_prepare(container, selected_only=True)
    status = _document_status_payload(container)
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
    return SessionHistoryResponse(
        session_id=session_id,
        messages=container.session_service.get_history(session_id),
    )


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    container: AppContainer = Depends(get_container),
) -> QueryResponse:
    if payload.source_files is not None:
        container.document_ingestion_service.select_sources(payload.source_files)
    return container.pipeline_service.answer_question(payload)


@router.post("/query/stream")
async def query_stream(
    payload: QueryRequest,
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    if payload.source_files is not None:
        container.document_ingestion_service.select_sources(payload.source_files)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'status', 'message': 'processing'}, ensure_ascii=False)}\n\n"
        try:
            response = container.pipeline_service.answer_question(payload)
            yield f"data: {json.dumps({'type': 'result', 'payload': response.model_dump()}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': _format_stream_error(exc)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest,
    container: AppContainer = Depends(get_container),
) -> FeedbackResponse:
    record = container.feedback_service.save_feedback(payload)
    return FeedbackResponse(message="Feedback saved", feedback_id=record["feedback_id"])
