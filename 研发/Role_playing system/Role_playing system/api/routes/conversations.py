# -*- coding: utf-8 -*-
"""
会话与聊天路由模块
功能：提供会话管理和聊天交互的 API 接口。
包括创建会话、重命名、删除、聊天、获取历史记录等。

接口列表：
  - POST /api/conversations/create: 创建新会话
  - PATCH /api/conversations/{id}: 重命名会话
  - DELETE /api/conversations/{id}: 删除会话
  - POST /api/chat: 发送聊天消息（核心接口）
  - GET /api/conversations/{id}/history: 获取会话历史
  - GET /api/users/{id}/conversations: 获取用户会话列表

依赖：
  - chat_rate_limiter: 聊天频率限制（按用户）
  - chat_ip_rate_limiter: 聊天频率限制（按 IP）
  - get_current_user: 用户认证
  - ChatBot: 业务逻辑层
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from chat_bot import ChatBot

from ..dependencies import assert_user_scope, chat_ip_rate_limiter, chat_rate_limiter, enforce_rate_limit, get_client_ip, get_current_user, raise_http_error
from ..schemas import ChatRequest, ConversationCreate, ConversationRename

router = APIRouter()


@router.post("/api/conversations/create")
async def create_conversation(conv: ConversationCreate, current_user: dict = Depends(get_current_user)):
    """
    创建新会话。
    
    为当前用户创建一个指定角色类型的新会话。
    
    Args:
        conv: 会话创建信息（角色类型、可选标题）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含新会话 ID 的响应
    """
    chat_bot = ChatBot()
    try:
        assert_user_scope(conv.user_id, current_user)
        conversation = chat_bot.create_conversation(current_user["user_id"], conv.role_type, conv.title)
        return {"code": 200, "message": "会话创建成功", "data": {"conversation_id": conversation.id}}
    except Exception as exc:
        raise_http_error("Create conversation", exc)
    finally:
        chat_bot.close()


@router.patch("/api/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: int,
    payload: ConversationRename,
    current_user: dict = Depends(get_current_user),
):
    """
    重命名会话。
    
    修改指定会话的标题，仅限会话所有者操作。
    
    Args:
        conversation_id: 会话 ID
        payload: 新标题
        current_user: 当前认证用户
        
    Returns:
        dict: 包含更新后会话信息的响应
    """
    chat_bot = ChatBot()
    try:
        conversation = chat_bot.rename_conversation(
            conversation_id,
            payload.title,
            user_id=current_user["user_id"],
        )
        return {
            "code": 200,
            "message": "会话重命名成功",
            "data": {"conversation_id": conversation.id, "title": conversation.title},
        }
    except Exception as exc:
        raise_http_error("Rename conversation", exc)
    finally:
        chat_bot.close()


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """
    删除会话。
    
    删除指定会话及其所有消息，仅限会话所有者操作。
    
    Args:
        conversation_id: 会话 ID
        current_user: 当前认证用户
        
    Returns:
        dict: 包含已删除会话 ID 的响应
    """
    chat_bot = ChatBot()
    try:
        chat_bot.delete_conversation(conversation_id, user_id=current_user["user_id"])
        return {"code": 200, "message": "会话已删除", "data": {"conversation_id": conversation_id}}
    except Exception as exc:
        raise_http_error("Delete conversation", exc)
    finally:
        chat_bot.close()


@router.post("/api/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    发送聊天消息（核心接口）。
    
    处理用户的聊天请求，涉及 RAG 检索和 LLM 调用。
    受双重速率限制保护（按用户 + 按 IP）。
    
    Args:
        request: 聊天请求（会话 ID、消息内容、可选客户端请求 ID）
        http_request: HTTP 请求对象（用于获取客户端 IP）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含 LLM 回复的响应
    """
    enforce_rate_limit(
        chat_rate_limiter,
        f"chat:user:{current_user['user_id']}",
        "聊天请求过于频繁，请稍后再试。",
    )
    enforce_rate_limit(
        chat_ip_rate_limiter,
        f"chat:ip:{get_client_ip(http_request)}",
        "当前 IP 的聊天请求过于频繁，请稍后再试。",
    )
    chat_bot = ChatBot()
    if request.stream:
        async def event_stream():
            try:
                for event in chat_bot.stream_chat(
                    request.conversation_id,
                    request.message,
                    client_request_id=request.client_request_id,
                    user_id=current_user["user_id"],
                ):
                    if await http_request.is_disconnected():
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)
            except Exception as exc:
                error_payload = {"type": "error", "message": str(exc)}
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            finally:
                chat_bot.close()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    try:
        result = chat_bot.chat(
            request.conversation_id,
            request.message,
            client_request_id=request.client_request_id,
            user_id=current_user["user_id"],
        )
        return {"code": 200, "message": "success", "data": result}
    except Exception as exc:
        raise_http_error("Chat request", exc)
    finally:
        chat_bot.close()


@router.get("/api/conversations/{conversation_id}/history")
async def get_history(
    conversation_id: int,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """
    获取会话历史。
    
    加载指定会话的消息历史记录，支持限制返回条数。
    
    Args:
        conversation_id: 会话 ID
        limit: 返回消息条数上限（默认 20）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含消息历史列表的响应
    """
    chat_bot = ChatBot()
    try:
        history = chat_bot.get_conversation_history(conversation_id, limit, user_id=current_user["user_id"])
        return {"code": 200, "message": "success", "data": history}
    except Exception as exc:
        raise_http_error("Get conversation history", exc)
    finally:
        chat_bot.close()


@router.get("/api/users/{user_id}/conversations")
async def get_user_conversations(user_id: int, current_user: dict = Depends(get_current_user)):
    """
    获取用户会话列表。
    
    列出当前用户的所有会话。
    
    Args:
        user_id: 用户 ID（用于权限验证）
        current_user: 当前认证用户
        
    Returns:
        dict: 包含会话列表的响应
    """
    chat_bot = ChatBot()
    try:
        assert_user_scope(user_id, current_user)
        conversations = chat_bot.get_user_conversations(current_user["user_id"])
        return {"code": 200, "message": "success", "data": conversations}
    except Exception as exc:
        raise_http_error("List user conversations", exc)
    finally:
        chat_bot.close()
