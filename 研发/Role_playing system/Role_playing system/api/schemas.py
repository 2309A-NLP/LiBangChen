# -*- coding: utf-8 -*-
"""
请求数据模型（Pydantic Schemas）
功能：定义所有 API 请求的请求体数据模型，使用 Pydantic 进行数据验证。
每个模型对应一个 API 端点的请求体结构。

模型列表：
  - UserCreate: 用户注册请求
  - UserLogin: 用户登录请求
  - ConversationCreate: 创建会话请求
  - ConversationRename: 重命名会话请求
  - ChatRequest: 聊天请求
  - KnowledgeDocumentCreate: 添加知识文档请求
  - LLMConfigPayload: LLM 配置更新请求
  - RetrievalConfigPayload: 检索配置更新请求
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    """用户注册请求体。"""
    username: str
    password: str
    email: Optional[str] = None


class UserLogin(BaseModel):
    """用户登录请求体。"""
    username: str
    password: str


class ConversationCreate(BaseModel):
    """创建会话请求体。"""
    user_id: Optional[int] = None
    role_type: str
    title: Optional[str] = None


class ConversationRename(BaseModel):
    """重命名会话请求体。"""
    title: str


class ChatRequest(BaseModel):
    """聊天请求体。"""
    conversation_id: int
    message: str
    client_request_id: Optional[str] = None
    stream: Optional[bool] = False


class KnowledgeDocumentCreate(BaseModel):
    """添加知识文档请求体。"""
    title: str
    content: str
    source: str
    role_type: str


class LLMConfigPayload(BaseModel):
    """LLM 配置更新请求体。"""
    model_name: str
    api_key: str
    api_base: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_seconds: Optional[float] = None


class RetrievalConfigPayload(BaseModel):
    """检索配置更新请求体。"""
    mode: str
    compare_mode: Optional[bool] = None
    compare_modes: Optional[list[str]] = None
    auto_mode_enabled: Optional[bool] = None
    enable_rerank: Optional[bool] = None
