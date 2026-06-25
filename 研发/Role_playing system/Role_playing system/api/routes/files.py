# -*- coding: utf-8 -*-
"""
文件管理路由模块
功能：提供文件上传、管理、角色分析等 API 接口。
支持 PDF、图片等文件的上传和解析，以及基于文件内容的角色推荐。

接口列表：
  - GET /api/conversations/{id}/files: 获取会话文件列表
  - POST /api/files/upload: 上传文件到会话
  - POST /api/files/analyze-role: 分析文件并推荐角色
  - DELETE /api/files/{id}: 删除已上传文件

依赖：
  - upload_rate_limiter: 上传频率限制
  - analyze_rate_limiter: 分析频率限制
  - get_current_user: 用户认证
  - ChatBot: 业务逻辑层
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from chat_bot import ChatBot

from ..dependencies import analyze_rate_limiter, assert_user_scope, enforce_rate_limit, get_client_ip, get_current_user, raise_http_error, upload_rate_limiter

router = APIRouter()


@router.get("/api/conversations/{conversation_id}/files")
async def get_conversation_files(
    conversation_id: int,
    user_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    获取会话文件列表。
    
    列出指定会话中已上传的所有文件。
    
    Args:
        conversation_id: 会话 ID
        user_id: 用户 ID（用于权限验证）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含文件列表的响应
    """
    chat_bot = ChatBot()
    try:
        assert_user_scope(user_id, current_user)
        files = chat_bot.list_conversation_files(current_user["user_id"], conversation_id)
        return {"code": 200, "message": "success", "data": files}
    except Exception as exc:
        raise_http_error("List conversation files", exc)
    finally:
        chat_bot.close()


@router.post("/api/files/upload")
async def upload_file(
    current_user: dict = Depends(get_current_user),
    user_id: Optional[int] = Form(None),
    conversation_id: int = Form(...),
    file: UploadFile = File(...),
):
    """
    上传文件到会话。
    
    支持 PDF、图片等文件格式，上传后自动解析内容。
    受上传频率限制保护。
    
    Args:
        current_user: 当前认证用户
        user_id: 用户 ID（用于权限验证）
        conversation_id: 目标会话 ID
        file: 上传的文件
        
    Returns:
        dict: 包含解析后文件信息的响应
    """
    assert_user_scope(user_id, current_user)
    enforce_rate_limit(
        upload_rate_limiter,
        f"upload:user:{current_user['user_id']}",
        "文件上传过于频繁，请稍后再试。",
    )
    chat_bot = ChatBot()
    try:
        file_bytes = await file.read()
        data = chat_bot.upload_conversation_file(
            user_id=current_user["user_id"],
            conversation_id=conversation_id,
            filename=file.filename or "",
            content_type=file.content_type or "",
            file_bytes=file_bytes,
        )
        return {"code": 200, "message": "文件上传并解析成功", "data": data}
    except Exception as exc:
        raise_http_error("Upload file", exc)
    finally:
        chat_bot.close()


@router.post("/api/files/analyze-role")
async def analyze_file_role(
    http_request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    分析文件并推荐角色。
    
    通过 LLM 分析文件内容，推荐最匹配的角色类型。
    受双重速率限制保护（按用户 + 按 IP）。
    
    Args:
        http_request: HTTP 请求对象（用于获取客户端 IP）
        file: 待分析的文件
        current_user: 当前认证用户
        
    Returns:
        dict: 包含推荐角色信息的响应
    """
    enforce_rate_limit(
        analyze_rate_limiter,
        f"analyze:user:{current_user['user_id']}",
        "文件分析过于频繁，请稍后再试。",
    )
    enforce_rate_limit(
        analyze_rate_limiter,
        f"analyze:ip:{get_client_ip(http_request)}",
        "当前 IP 的文件分析请求过于频繁，请稍后再试。",
    )
    chat_bot = ChatBot()
    try:
        file_bytes = await file.read()
        data = chat_bot.analyze_file_role(file.filename or "", file_bytes)
        return {"code": 200, "message": "文件角色分析完成", "data": data}
    except Exception as exc:
        raise_http_error("Analyze file role", exc)
    finally:
        chat_bot.close()


@router.delete("/api/files/{file_id}")
async def delete_uploaded_file(
    file_id: int,
    user_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    删除已上传文件。
    
    删除指定文件，仅限文件所有者操作。
    
    Args:
        file_id: 文件 ID
        user_id: 用户 ID（用于权限验证）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含已删除文件 ID 的响应
    """
    chat_bot = ChatBot()
    try:
        assert_user_scope(user_id, current_user)
        chat_bot.delete_uploaded_file(current_user["user_id"], file_id)
        return {"code": 200, "message": "文件已删除", "data": {"file_id": file_id}}
    except Exception as exc:
        raise_http_error("Delete uploaded file", exc)
    finally:
        chat_bot.close()
