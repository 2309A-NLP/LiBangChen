"""
LLM API 调用封装
=================
封装 SiliconFlow 的 OpenAI 兼容 API 调用，支持 Function Calling。
- 支持自动重试（指数退避）
- 请求级 SSL 上下文（不再全局 monkey-patch）
- 结构化日志记录

工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务
"""

import json
import ssl
import time
import certifi
from urllib import error, request
from typing import Any

from config import (
    API_KEY,
    BASE_URL,
    MODEL,
    TEMPERATURE,
    MAX_TOKENS,
    TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF,
    get_logger,
)

logger = get_logger(__name__)

# ── SSL 上下文（请求级别，非全局） ──────────────────────────────────────────────

def _create_ssl_context() -> ssl.SSLContext:
    """创建请求级别的 SSL 上下文，不影响全局设置。"""
    return ssl.create_default_context(cafile=certifi.where())


# ── API 调用 ──────────────────────────────────────────────────────────────────

def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """调用 SiliconFlow Chat Completions API，失败自动重试。

    Args:
        messages: 对话消息列表
        tools: Function Calling 工具定义（可选）
        temperature: 采样温度 (0.0-1.0)
        max_tokens: 最大输出 token 数

    Returns:
        API 响应的 JSON dict

    Raises:
        RuntimeError: 所有重试均失败
        ValueError: API_KEY 未配置
    """
    if not API_KEY:
        raise ValueError(
            "API Key 未配置。请设置环境变量 SILICONFLOW_API_KEY\n"
            "  Windows (PowerShell): $env:SILICONFLOW_API_KEY='sk-...'\n"
            "  Linux/macOS: export SILICONFLOW_API_KEY='sk-...'"
        )

    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode("utf-8")
    url = f"{BASE_URL}/chat/completions"

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
                method="POST",
            )

            # 请求级别 SSL 上下文
            ssl_context = _create_ssl_context()
            resp = request.urlopen(req, timeout=TIMEOUT, context=ssl_context)
            result = json.loads(resp.read().decode("utf-8"))

            # 记录 token 用量（如有）
            usage = result.get("usage", {})
            if usage:
                logger.debug(
                    "API 调用成功 (attempt=%d): prompt=%d, completion=%d, total=%d",
                    attempt,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    usage.get("total_tokens", 0),
                )
            return result

        except error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"API HTTP {e.code}: {body}")

            # 4xx 客户端错误不重试（401/403/404 等）
            if 400 <= e.code < 500:
                logger.error("API 客户端错误 (HTTP %d): %s", e.code, body)
                raise last_error

            logger.warning("API 服务端错误 (attempt=%d/%d): HTTP %d", attempt, MAX_RETRIES, e.code)

        except Exception as e:
            last_error = RuntimeError(f"API 请求失败: {e}")
            logger.warning("API 请求异常 (attempt=%d/%d): %s", attempt, MAX_RETRIES, e)

        # 最后一次尝试不等待
        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF ** attempt
            logger.debug("等待 %.1fs 后重试...", wait)
            time.sleep(wait)

    logger.error("API 调用最终失败，已重试 %d 次", MAX_RETRIES)
    raise last_error  # type: ignore[misc]
