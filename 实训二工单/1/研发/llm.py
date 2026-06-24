"""
LLM API 调用封装
=================
封装 SiliconFlow 的 OpenAI 兼容 API，支持流式输出。
工单编号: 人工智能NLP-Agent数字人项目-记账本任务
"""

import json
import ssl
import sys
from urllib import error, request
from typing import Any

import certifi

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

API_KEY = "sk-anzqeikgpjjcxueqwmhcrrmfbwssndlxvughyfcztwbpeefv"
BASE_URL = "https://api.siliconflow.cn/v1"
# Qwen3-14B
MODEL = "Qwen/Qwen3-14B"
TIMEOUT = 60


def chat_completion(
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    stream: bool = False,
    tool_choice: str = "auto",
) -> dict[str, Any] | str:
    """
    调用 SiliconFlow 对话 API。

    支持：
    - function calling（tools 参数）
    - 流式输出（stream=True，返回完整 content 字符串）
    非流式模式返回完整 API 响应字典。
    """
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{BASE_URL}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "Accept": "text/event-stream" if stream else "application/json",
        },
        method="POST",
    )

    try:
        resp = request.urlopen(req, timeout=TIMEOUT)

        if stream:
            return _read_sse(resp)
        else:
            return json.loads(resp.read().decode("utf-8"))

    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"API 请求失败: {e}")


def _read_sse(resp) -> str:
    """
    读取 SSE (Server-Sent Events) 流，逐 token 打印并累积返回完整文本。
    """
    full_content = ""
    buffer = ""

    while True:
        chunk = resp.read(4096)  # 一次读 4KB，避免逐字节低效
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")

        # SSE 事件以 \n\n 分隔
        if "\n\n" in buffer:
            lines = buffer.split("\n\n")
            for line in lines[:-1]:
                line = line.strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            full_content += delta
                            print(delta, end="", flush=True)
                    except json.JSONDecodeError:
                        pass
            buffer = lines[-1]

    print()  # 换行
    return full_content
