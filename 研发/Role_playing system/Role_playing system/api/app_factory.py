# -*- coding: utf-8 -*-
"""
FastAPI 应用工厂
功能：创建和配置 FastAPI 应用实例，注册所有中间件和路由。
作为 API 层的入口，负责：
  1. 创建 FastAPI 实例
  2. 注册 CORS 和 TrustedHost 中间件
  3. 添加 HTTP 请求日志中间件
  4. 注册所有路由模块（auth, conversations, files, knowledge, llm, system）
  5. 配置应用生命周期（启动/关闭）

主要函数：
  - create_app(): 创建并配置 FastAPI 应用实例
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import APP_CONFIG, UPLOAD_CONFIG
from console_utils import configure_console_encoding
from logging_utils import configure_logging, get_logger

from .dependencies import get_client_ip
from .routes.auth import router as auth_router
from .routes.conversations import router as conversation_router
from .routes.files import router as file_router
from .routes.knowledge import router as knowledge_router
from .routes.llm import router as llm_router
from .routes.system import router as system_router
from .services import lifespan

configure_console_encoding()
configure_logging()

logger = get_logger(__name__)
UPLOADS_DIR = UPLOAD_CONFIG["root_dir"]


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例。
    
    配置内容：
    1. CORS 中间件（允许跨域请求）
    2. TrustedHost 中间件（限制受信任的主机）
    3. HTTP 请求日志中间件（记录请求方法、路径、状态码、耗时）
    4. 注册 6 个路由模块：system, auth, conversations, files, knowledge, llm
    5. 应用生命周期管理（数据库初始化、知识同步调度）
    
    Returns:
        FastAPI: 配置好的 FastAPI 应用实例
    """
    app = FastAPI(
        title="Role_playing system API",
        description="基于 RAG 的多角色扮演系统",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=APP_CONFIG["cors_origins"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    trusted_hosts = APP_CONFIG["trusted_hosts"]
    if trusted_hosts and trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "HTTP request failed: method=%s path=%s client_ip=%s duration_ms=%s",
                request.method,
                request.url.path,
                get_client_ip(request),
                duration_ms,
            )
            raise

        return response

    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(conversation_router)
    app.include_router(file_router)
    app.include_router(knowledge_router)
    app.include_router(llm_router)
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

    return app


app = create_app()
