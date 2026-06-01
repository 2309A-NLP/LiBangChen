# -*- coding: utf-8 -*-
"""
知识库与检索路由模块
功能：提供知识库管理、知识同步、检索配置等 API 接口。
包括知识文档添加、知识同步触发、PDF 下载、Milvus 状态查询、检索模式配置等。

接口列表：
  - POST /api/knowledge/add: 手动添加知识文档（管理员）
  - POST /api/knowledge/crawl: 触发知识同步（管理员）
  - GET /api/knowledge/sync/status: 知识同步状态（管理员）
  - GET /api/knowledge/pdf/status: 知识 PDF 状态
  - GET /api/knowledge/pdf/download: 下载知识 PDF
  - GET /api/knowledge/milvus/status: Milvus 状态（管理员）
  - GET /api/retrieval/status: 检索配置状态（管理员）
  - POST /api/retrieval/config: 更新检索配置（管理员）

依赖：
  - require_admin: 管理员权限验证
  - get_current_user: 用户认证
  - knowledge_sync_manager: 知识同步管理器
  - MilvusStore: 向量数据库
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from chat_bot import ChatBot

from ..dependencies import BASE_DIR, KNOWLEDGE_PDF_PATH, get_current_user, raise_http_error, require_admin
from ..schemas import KnowledgeDocumentCreate, RetrievalConfigPayload
from ..services import build_knowledge_sync_status, get_knowledge_pdf_info, get_milvus_connection_info, knowledge_sync_manager

router = APIRouter()


def upsert_env_value(path, key: str, value: str) -> None:
    """
    持久化环境变量到 .env 文件。
    
    如果 key 已存在则更新值，否则追加新行。
    
    Args:
        path: .env 文件路径
        key: 环境变量名
        value: 环境变量值
    """
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    updated = False
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.post("/api/knowledge/add")
async def add_knowledge(doc: KnowledgeDocumentCreate, _: None = Depends(require_admin)):
    """
    手动添加知识文档（管理员）。
    
    将一条知识文档添加到知识库中，支持去重。
    
    Args:
        doc: 知识文档信息（标题、内容、来源、角色类型）
        
    Returns:
        dict: 添加结果（成功或已存在）
    """
    chat_bot = ChatBot()
    try:
        created = chat_bot.add_knowledge_document(doc.title, doc.content, doc.source, doc.role_type)
        message = "知识添加成功" if created else "知识已存在，未重复写入"
        return {"code": 200, "message": message}
    except Exception as exc:
        raise_http_error("Add knowledge", exc)
    finally:
        chat_bot.close()


@router.post("/api/knowledge/crawl")
async def crawl_knowledge(_: None = Depends(require_admin)):
    """
    触发知识同步（管理员）。
    
    立即执行一次知识同步，从知识源目录读取并处理文档。
    
    Returns:
        dict: 同步结果（处理数和新增数）
    """
    try:
        result = knowledge_sync_manager.run_once()
        return {
            "code": 200,
            "message": f"已处理 {result['processed_count']} 条知识，新增 {result['added_count']} 条",
            "data": result,
        }
    except Exception as exc:
        raise_http_error("Crawl knowledge", exc)


@router.get("/api/knowledge/sync/status")
async def get_knowledge_sync_status(_: None = Depends(require_admin)):
    """
    获取知识同步状态（管理员）。
    
    返回后台知识同步的当前状态信息。
    
    Returns:
        dict: 同步状态（包括 PDF 信息、角色汇编状态等）
    """
    return {"code": 200, "data": build_knowledge_sync_status()}


@router.get("/api/knowledge/pdf/status")
async def get_knowledge_pdf_status(current_user: dict = Depends(get_current_user)):
    """
    获取知识 PDF 状态。
    
    返回已生成的知识库 PDF 文件信息。
    
    Args:
        current_user: 当前认证用户
        
    Returns:
        dict: PDF 文件信息（是否存在、大小、更新时间等）
    """
    _ = current_user
    return {"code": 200, "data": get_knowledge_pdf_info()}


@router.get("/api/knowledge/pdf/download")
async def download_knowledge_pdf(current_user: dict = Depends(get_current_user)):
    """
    下载知识 PDF。
    
    下载已生成的知识库 PDF 文件。
    
    Args:
        current_user: 当前认证用户
        
    Returns:
        FileResponse: PDF 文件流
        
    Raises:
        404: PDF 文件不存在
    """
    _ = current_user
    if not KNOWLEDGE_PDF_PATH.exists():
        raise HTTPException(status_code=404, detail="PDF 知识库文件不存在，请先执行知识库同步。")
    return FileResponse(
        KNOWLEDGE_PDF_PATH,
        media_type="application/pdf",
        filename=KNOWLEDGE_PDF_PATH.name,
    )


@router.get("/api/knowledge/milvus/status")
async def get_milvus_status(_: None = Depends(require_admin)):
    """
    获取 Milvus 状态（管理员）。
    
    返回 Milvus 向量数据库的配置和运行状态。
    
    Returns:
        dict: Milvus 连接信息和运行时状态
    """
    return {"code": 200, "data": get_milvus_connection_info()}


@router.get("/api/retrieval/status")
async def get_retrieval_status(_: None = Depends(require_admin)):
    """
    获取检索配置状态（管理员）。
    
    返回当前检索模式的运行时配置和后端状态。
    
    Returns:
        dict: 检索配置状态
    """
    from vector_store import MilvusStore

    store = MilvusStore()
    return {"code": 200, "data": store.get_status()}


@router.post("/api/retrieval/config")
async def update_retrieval_config(payload: RetrievalConfigPayload, _: None = Depends(require_admin)):
    """
    更新检索配置（管理员）。
    
    修改检索模式（dense/sparse/bm25/hybrid/hybrid_rerank/auto）、
    比较模式、重排序等配置，并持久化到 .env 文件。
    
    Args:
        payload: 检索配置参数
        
    Returns:
        dict: 更新后的检索配置状态
    """
    from vector_store import MilvusStore

    normalized_mode = (payload.mode or "").strip().lower()
    compare_mode = bool(payload.compare_mode) if payload.compare_mode is not None else False
    compare_modes = payload.compare_modes or ["dense", "sparse", "bm25", "hybrid", "hybrid_rerank"]
    auto_mode_enabled = bool(payload.auto_mode_enabled) if payload.auto_mode_enabled is not None else False
    enable_rerank = bool(payload.enable_rerank) if payload.enable_rerank is not None else None

    os.environ["RETRIEVAL_MODE"] = normalized_mode
    os.environ["RETRIEVAL_COMPARE_MODE"] = "true" if compare_mode else "false"
    os.environ["RETRIEVAL_COMPARE_MODES"] = ",".join(compare_modes)
    os.environ["RETRIEVAL_AUTO_MODE_ENABLED"] = "true" if auto_mode_enabled else "false"
    if enable_rerank is not None:
        os.environ["ENABLE_RERANK"] = "true" if enable_rerank else "false"

    env_path = BASE_DIR / ".env"
    upsert_env_value(env_path, "RETRIEVAL_MODE", normalized_mode)
    upsert_env_value(env_path, "RETRIEVAL_COMPARE_MODE", "true" if compare_mode else "false")
    upsert_env_value(env_path, "RETRIEVAL_COMPARE_MODES", ",".join(compare_modes))
    upsert_env_value(env_path, "RETRIEVAL_AUTO_MODE_ENABLED", "true" if auto_mode_enabled else "false")
    if enable_rerank is not None:
        upsert_env_value(env_path, "ENABLE_RERANK", "true" if enable_rerank else "false")

    store = MilvusStore()
    store.retrieval_mode = store._normalize_retrieval_mode(normalized_mode)
    store.compare_mode_enabled = compare_mode
    store.compare_modes = [
        store._normalize_retrieval_mode(mode)
        for mode in compare_modes
        if store._normalize_retrieval_mode(mode) != "auto"
    ]
    store.auto_mode_enabled = auto_mode_enabled
    if enable_rerank is not None:
        store._load_reranker()

    return {
        "code": 200,
        "message": "检索配置已更新",
        "data": store.get_status(),
    }
