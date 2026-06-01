# -*- coding: utf-8 -*-
"""
系统与前端路由模块
功能：提供系统状态、角色列表、健康检查等基础 API 接口。
同时负责提供前端页面。

接口列表：
  - GET /: 提供前端页面（不包含在 OpenAPI 文档中）
  - GET /api/roles: 获取支持的角色列表
  - GET /health: 健康检查端点

依赖：
  - FRONTEND_PATH: 前端页面文件路径
  - ROLES: 角色配置
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import FileResponse

from config import ROLES

from ..dependencies import FRONTEND_PATH

router = APIRouter()


@router.get("/", include_in_schema=False)
async def home():
    """
    提供前端页面。
    
    返回打包好的前端 HTML 文件。
    此接口不在 OpenAPI 文档中显示。
    
    Returns:
        FileResponse: 前端 HTML 文件
    """
    return FileResponse(FRONTEND_PATH)


@router.get("/api/roles")
async def get_roles():
    """
    获取支持的角色列表。
    
    返回系统支持的所有角色类型及其配置信息。
    
    Returns:
        dict: 角色列表（如 doctor, lawyer, teacher 等）
    """
    return {"code": 200, "data": ROLES}


@router.get("/health")
async def health_check():
    """
    健康检查端点。
    
    用于监控系统运行状态。
    
    Returns:
        dict: 健康状态和时间戳
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
