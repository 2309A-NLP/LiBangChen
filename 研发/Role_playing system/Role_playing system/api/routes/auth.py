# -*- coding: utf-8 -*-
"""
认证路由模块
功能：提供用户注册和登录的 API 接口。
使用速率限制防止暴力破解和恶意注册。

接口列表：
  - POST /api/users/create: 创建用户（注册），返回 Bearer Token
  - POST /api/users/login: 用户登录，返回 Bearer Token

依赖：
  - register_rate_limiter: 注册频率限制（按 IP）
  - login_rate_limiter: 登录频率限制（按 IP）
  - ChatBot: 业务逻辑层
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from chat_bot import ChatBot

from ..dependencies import enforce_rate_limit, get_client_ip, issue_auth_payload, login_rate_limiter, raise_http_error, register_rate_limiter
from ..schemas import UserCreate, UserLogin

router = APIRouter()


@router.post("/api/users/create")
async def create_user(user: UserCreate, request: Request):
    """
    创建用户（注册）。
    
    注册成功后立即返回 Bearer Token，无需额外登录。
    受注册频率限制保护（按 IP）。
    
    Args:
        user: 用户注册信息（用户名、密码、可选邮箱）
        request: HTTP 请求对象（用于获取客户端 IP）
        
    Returns:
        dict: 包含用户信息和 Bearer Token 的响应
        
    Raises:
        429: 注册过于频繁
        409: 用户名已存在
    """
    enforce_rate_limit(
        register_rate_limiter,
        f"register:{get_client_ip(request)}",
        "注册过于频繁，请稍后再试。",
    )
    chat_bot = ChatBot()
    try:
        user_obj = chat_bot.create_user(user.username, user.password, user.email)
        return {
            "code": 200,
            "message": "用户创建成功",
            "data": issue_auth_payload(user_obj),
        }
    except Exception as exc:
        raise_http_error("Create user", exc)
    finally:
        chat_bot.close()


@router.post("/api/users/login")
async def login_user(user: UserLogin, request: Request):
    """
    用户登录。
    
    验证用户名和密码，成功后返回 Bearer Token。
    受登录频率限制保护（按 IP）。
    
    Args:
        user: 用户登录信息（用户名、密码）
        request: HTTP 请求对象（用于获取客户端 IP）
        
    Returns:
        dict: 包含用户信息和 Bearer Token 的响应
        
    Raises:
        429: 登录尝试过于频繁
        401: 用户名或密码错误
    """
    enforce_rate_limit(
        login_rate_limiter,
        f"login:{get_client_ip(request)}",
        "登录尝试过于频繁，请稍后再试。",
    )
    chat_bot = ChatBot()
    try:
        user_obj = chat_bot.authenticate_user(user.username, user.password)
        return {
            "code": 200,
            "message": "登录成功",
            "data": issue_auth_payload(user_obj),
        }
    except Exception as exc:
        raise_http_error("Login user", exc)
    finally:
        chat_bot.close()
