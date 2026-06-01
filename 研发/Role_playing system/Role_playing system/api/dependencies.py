# -*- coding: utf-8 -*-
"""
API 依赖与辅助工具
功能：提供 API 路由共享的依赖注入、速率限制、认证验证、错误处理等工具。
作为 API 层的公共基础设施，所有路由模块通过此模块获取通用功能。

主要函数：
  - get_client_ip(): 获取客户端 IP（支持代理头）
  - issue_auth_payload(): 构建认证响应载荷
  - extract_bearer_token(): 解析 Bearer Token
  - enforce_rate_limit(): 强制执行速率限制
  - assert_user_scope(): 验证用户操作权限
  - get_current_user(): 获取当前认证用户
  - require_admin(): 管理员权限验证
  - http_error(): 业务异常转 HTTP 异常
  - raise_http_error(): 记录日志并抛出 HTTP 异常

全局速率限制器：
  - login_rate_limiter: 登录频率限制
  - register_rate_limiter: 注册频率限制
  - chat_rate_limiter: 聊天频率限制
  - chat_ip_rate_limiter: 聊天 IP 频率限制
  - upload_rate_limiter: 上传频率限制
  - analyze_rate_limiter: 分析频率限制
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException, Request

from chat_bot import ChatBot, DuplicateUsernameError
from config import AUTH_CONFIG, SECURITY_CONFIG
from logging_utils import get_logger
from security import FixedWindowRateLimiter, issue_access_token, verify_access_token, verify_admin_api_key

logger = get_logger(__name__)

# 项目根目录和静态文件路径
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_PATH = BASE_DIR / "frontend" / "index.html"  # 前端页面路径
KNOWLEDGE_PDF_PATH = BASE_DIR / "generated" / "knowledge_base" / "roleplay_knowledge_base.pdf"  # 知识库 PDF 路径

# Token 过期时间（秒）
TOKEN_EXPIRE_SECONDS = AUTH_CONFIG["token_expire_hours"] * 3600
ADMIN_HEADER_NAME = "X-Admin-Key"  # 管理员 API Key 请求头名称

# 速率限制器实例
login_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["login_rate_limit_per_minute"], 60)
register_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["register_rate_limit_per_hour"], 3600)
chat_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["chat_rate_limit_per_minute"], 60)
chat_ip_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["chat_ip_rate_limit_per_minute"], 60)
upload_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["upload_rate_limit_per_minute"], 60)
analyze_rate_limiter = FixedWindowRateLimiter(SECURITY_CONFIG["analyze_rate_limit_per_minute"], 60)


def get_client_ip(request: Request) -> str:
    """
    获取客户端 IP 地址。
    
    优先使用 X-Forwarded-For 头（代理场景），
    其次使用 X-Real-IP 头，
    最后回退到 request.client.host。
    
    Args:
        request: FastAPI 请求对象
        
    Returns:
        str: 客户端 IP 地址
    """
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    client = request.client
    return client.host if client else "unknown"


def issue_auth_payload(user_obj: Any) -> dict:
    """Build the auth payload returned after login or registration."""
    return {
        "user_id": user_obj.id,
        "username": user_obj.username,
        "access_token": issue_access_token(user_obj.id, user_obj.username, TOKEN_EXPIRE_SECONDS),
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRE_SECONDS,
    }


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Parse the Authorization header and return a bearer token when present."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def enforce_rate_limit(limiter: FixedWindowRateLimiter, key: str, detail: str) -> None:
    """Raise 429 when the caller exceeds the configured limit."""
    allowed, retry_after = limiter.check(key)
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def assert_user_scope(requested_user_id: Optional[int], current_user: dict) -> None:
    """Reject attempts to operate on another user's resources."""
    if requested_user_id is None:
        return
    if int(requested_user_id) != int(current_user["user_id"]):
        raise HTTPException(status_code=403, detail="不能操作其他用户的数据。")


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Validate the bearer token and return the current user identity."""
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录后再访问该接口。")

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")

    chat_bot = ChatBot()
    try:
        user_obj = chat_bot.get_active_user(int(payload["sub"]))
        return {"user_id": user_obj.id, "username": user_obj.username}
    except Exception as exc:
        logger.warning("Failed to resolve current user from token: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    finally:
        chat_bot.close()


async def require_admin(admin_key: Optional[str] = Header(default=None, alias=ADMIN_HEADER_NAME)) -> None:
    """Protect management endpoints with an environment-based admin key."""
    if not AUTH_CONFIG["admin_api_key"]:
        raise HTTPException(status_code=503, detail="管理员密钥未配置，该接口已禁用。")
    if not verify_admin_api_key(admin_key):
        raise HTTPException(status_code=403, detail="管理员密钥无效。")


def http_error(exc: Exception) -> HTTPException:
    """Normalize business exceptions into stable HTTP errors."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, DuplicateUsernameError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def raise_http_error(action: str, exc: Exception) -> None:
    """Log and raise a normalized HTTP exception."""
    normalized = http_error(exc)
    if normalized.status_code >= 500:
        logger.exception("%s failed: %s", action, normalized.detail)
    else:
        logger.warning("%s failed: %s", action, normalized.detail)
    raise normalized from exc
