 # -*- coding: utf-8 -*-
"""
API 服务与生命周期管理
功能：提供 API 层的共享服务，包括应用生命周期管理、知识同步调度、
Milvus 连接状态检查、知识 PDF 信息查询等。

主要函数：
  - lifespan(): FastAPI 应用生命周期（启动/关闭）
  - get_knowledge_pdf_info(): 知识库 PDF 文件信息
  - get_role_compendium_info(): 各角色知识汇编文件状态
  - get_milvus_connection_info(): Milvus 连接状态
  - build_knowledge_sync_status(): 知识同步状态聚合

全局变量：
  - knowledge_sync_manager: 知识同步管理器单例
  - sync_knowledge_base: 知识同步函数引用
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import socket
from typing import Any

from fastapi import FastAPI

from config import KNOWLEDGE_SYNC_CONFIG, MILVUS_CONFIG, ROLES
from knowledge_sources import ensure_knowledge_source_directories, get_knowledge_source_status
from knowledge_sync import KnowledgeSyncManager
from knowledge_sync_service import sync_knowledge_documents
from models import init_database

from .dependencies import BASE_DIR, KNOWLEDGE_PDF_PATH

sync_knowledge_base = sync_knowledge_documents
knowledge_sync_manager = KnowledgeSyncManager(sync_knowledge_base)


def get_knowledge_pdf_info() -> dict:
    """Return metadata about the generated knowledge PDF."""
    exists = KNOWLEDGE_PDF_PATH.exists()
    stat = KNOWLEDGE_PDF_PATH.stat() if exists else None
    return {
        "exists": exists,
        "path": str(KNOWLEDGE_PDF_PATH),
        "filename": KNOWLEDGE_PDF_PATH.name,
        "size_bytes": stat.st_size if stat else 0,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat() if stat else None,
        "download_url": "/api/knowledge/pdf/download" if exists else None,
    }


def get_role_compendium_info() -> dict:
    """Return per-role compendium file status."""
    base_dir = BASE_DIR / "generated" / "domain_pdfs"
    roles: dict[str, Any] = {}
    for role_type in ROLES.keys():
        if role_type == "custom_persona":
            continue
        pdf_path = base_dir / f"{role_type}_compendium.pdf"
        entries_path = base_dir / f"{role_type}_entries.jsonl"
        roles[role_type] = {
            "pdf_exists": pdf_path.exists(),
            "pdf_path": str(pdf_path),
            "entries_exists": entries_path.exists(),
            "entries_path": str(entries_path),
            "entry_count": sum(1 for _ in entries_path.open("r", encoding="utf-8")) if entries_path.exists() else 0,
        }
    return {"base_dir": str(base_dir), "roles": roles}


def get_milvus_connection_info() -> dict:
    """Return Milvus configuration and a lightweight TCP connectivity check."""
    host = MILVUS_CONFIG["host"]
    port = int(MILVUS_CONFIG["port"])
    connected = False
    error = None
    if MILVUS_CONFIG["enabled"] and not MILVUS_CONFIG["uri"]:
        try:
            with socket.create_connection((host, port), timeout=min(float(MILVUS_CONFIG["timeout"]), 5.0)):
                connected = True
        except OSError as exc:
            error = str(exc)

    from vector_store import MilvusStore

    store = MilvusStore()
    return {
        "enabled": MILVUS_CONFIG["enabled"],
        "uri": MILVUS_CONFIG["uri"] or None,
        "host": host,
        "port": port,
        "collection_name": MILVUS_CONFIG["collection_name"],
        "user_collection_name": MILVUS_CONFIG["user_collection_name"],
        "db_name": MILVUS_CONFIG["db_name"] or None,
        "secure": MILVUS_CONFIG["secure"],
        "tcp_reachable": connected if MILVUS_CONFIG["enabled"] and not MILVUS_CONFIG["uri"] else None,
        "tcp_error": error,
        "runtime": store.get_status(),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize persistent services on startup and stop background jobs on shutdown."""
    init_database()
    ensure_knowledge_source_directories()
    if KNOWLEDGE_SYNC_CONFIG["enabled"]:
        knowledge_sync_manager.start()
    try:
        yield
    finally:
        knowledge_sync_manager.stop()


def build_knowledge_sync_status() -> dict:
    """Return the knowledge sync status payload."""
    return {
        **knowledge_sync_manager.get_status(),
        "pdf": get_knowledge_pdf_info(),
        "role_compendiums": get_role_compendium_info(),
        "knowledge_sources": get_knowledge_source_status(),
    }
