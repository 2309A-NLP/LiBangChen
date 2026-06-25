# -*- coding: utf-8 -*-
"""
LiveTalking RAG桥接模块
=======================
连接教育RAG后端（角色扮演系统）到LiveTalking数字人。

架构:
  用户问题 → RAG系统 /api/chat?stream=true (SSE)
           → RAG检索教育知识库
           → RAG构建Prompt
           → RAG调用LLM生成回答
           → SSE流式返回 → LiveTalking分句播报

使用方式:
  1. 启动RAG后端: cd E:/Role_playing system1/Role_playing system && python run.py serve
  2. 启动LiveTalking: python app.py --transport webrtc --model wav2lip ...

环境变量:
  RAG_API_URL      - RAG后端地址 (默认 http://127.0.0.1:8000)
  RAG_USERNAME     - RAG登录用户名 (默认 123456)
  RAG_PASSWORD     - RAG登录密码 (默认 123456)
  RAG_ROLE_TYPE    - 会话角色类型 (默认 teacher)
  RAG_TIMEOUT      - 请求超时秒数 (默认 30)
"""

import json
import os
import time
from typing import TYPE_CHECKING, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar

from utils.logger import logger

# ---- 配置 ----
RAG_API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
RAG_USERNAME = os.getenv("RAG_USERNAME", "123456")
RAG_PASSWORD = os.getenv("RAG_PASSWORD", "123456")
RAG_ROLE_TYPE = os.getenv("RAG_ROLE_TYPE", "teacher")
RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "30"))

# ---- 模块级缓存（一次性初始化） ----
_token: Optional[str] = None
_conversation_id: Optional[int] = None
_user_id: Optional[int] = None


def _ensure_initialized():
    """确保已登录并创建会话（只执行一次）"""
    global _token, _conversation_id, _user_id
    if _token is not None and _conversation_id is not None:
        return

    logger.info("[RAG] 初始化: 登录 + 创建会话...")

    # Step 1: 登录
    try:
        payload = json.dumps({
            "username": RAG_USERNAME,
            "password": RAG_PASSWORD,
        }).encode("utf-8")
        req = urllib_request.Request(
            f"{RAG_API_URL}/api/users/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib_request.urlopen(req, timeout=RAG_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        _token = data["data"]["access_token"]
        _user_id = data["data"]["user_id"]
        logger.info(f"[RAG] 登录成功, user_id={_user_id}")
    except Exception as e:
        logger.error(f"[RAG] 登录失败: {e}")
        raise

    # Step 2: 创建会话
    try:
        payload = json.dumps({"role_type": RAG_ROLE_TYPE}).encode("utf-8")
        req = urllib_request.Request(
            f"{RAG_API_URL}/api/conversations/create",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token}",
            },
            method="POST",
        )
        resp = urllib_request.urlopen(req, timeout=RAG_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        _conversation_id = data["data"]["conversation_id"]
        logger.info(f"[RAG] 会话创建成功, conversation_id={_conversation_id}")
    except Exception as e:
        logger.error(f"[RAG] 创建会话失败: {e}")
        raise


def llm_rag_response(message: str, avatar_session: 'BaseAvatar', datainfo: dict = {}):
    """
    RAG增强的LLM回复函数 —— 替代原版 llm_response。

    流程:
      1. 首次调用时自动登录RAG并创建会话（缓存token和conversation_id）
      2. 请求RAG后端的 /api/chat (SSE流式)
      3. 实时读取SSE数据块（type=delta事件）
      4. 按标点符号分句
      5. 逐句推送给数字人播报 (put_msg_txt)

    Args:
        message: 用户输入文本
        avatar_session: 数字人会话对象
        datainfo: 透传数据 (TTS参数等)
    """
    try:
        _ensure_initialized()

        start = time.perf_counter()
        logger.info(f"[RAG] 收到问题: {message[:80]}...")

        # 构建RAG流式聊天请求
        payload = json.dumps({
            "conversation_id": _conversation_id,
            "message": message,
            "stream": True,
        }).encode("utf-8")

        req = urllib_request.Request(
            f"{RAG_API_URL}/api/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        resp = urllib_request.urlopen(req, timeout=RAG_TIMEOUT)
        logger.info(f"[RAG] 连接成功, 耗时 {time.perf_counter() - start:.2f}s")

        # 读取SSE流式响应
        full_text = ""
        buffer = ""
        first = True

        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")

            # 按SSE事件边界 (\n\n) 分割
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    break

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "status":
                    msg = event.get("message", "")
                    if msg:
                        logger.info(f"[RAG] 状态: {msg}")
                    continue

                if event_type == "delta":
                    delta = event.get("delta", "")
                    full_text += delta

                    if first and delta:
                        logger.info(
                            f"[RAG] 首token耗时 {time.perf_counter() - start:.2f}s"
                        )
                        first = False

                    # 按标点分句推送给数字人
                    full_text = _flush_sentences(full_text, avatar_session, datainfo)

                if event_type == "error":
                    err_msg = event.get("message", "未知错误")
                    logger.error(f"[RAG] 服务端错误: {err_msg}")
                    _fallback_direct_llm(message, avatar_session, datainfo)
                    return

                if event_type == "done":
                    # 完整回复已包含在delta累积中
                    logger.info(f"[RAG] 流式完成")

        # 推送剩余文本
        if full_text.strip():
            avatar_session.put_msg_txt(full_text, datainfo)

        elapsed = time.perf_counter() - start
        logger.info(f"[RAG] 完成, 总耗时 {elapsed:.2f}s")

    except urllib_error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        logger.error(f"[RAG] HTTP错误 {e.code}: {body}")
        _fallback_direct_llm(message, avatar_session, datainfo)

    except Exception as e:
        logger.error(f"[RAG] 异常: {e}")
        _fallback_direct_llm(message, avatar_session, datainfo)


def _flush_sentences(text: str, avatar_session: 'BaseAvatar', datainfo: dict) -> str:
    """
    按标点符号分句，将完整句子推送给数字人播报。

    对标点符号: ,.!;:，。！？：；
    每句至少10个字符才推送（避免碎片化）。
    """
    last_pos = 0
    for i, char in enumerate(text):
        if char in ",.!;:，。！？：；":
            sentence = text[last_pos : i + 1]
            last_pos = i + 1
            if len(sentence.strip()) >= 10:
                logger.info(f"[RAG] 推送句子: {sentence}")
                avatar_session.put_msg_txt(sentence, datainfo)
    return text[last_pos:]


def _fallback_direct_llm(
    message: str, avatar_session: 'BaseAvatar', datainfo: dict
):
    """
    RAG不可用时的降级方案: 回退到原版DashScope直调。
    """
    logger.warning("[RAG] 降级为原版LLM直调...")
    try:
        from llm import llm_response
        llm_response(message, avatar_session, datainfo)
    except Exception as e:
        logger.error(f"[RAG] 降级也失败: {e}")
        avatar_session.put_msg_txt(
            "抱歉，我暂时无法回答这个问题，请稍后再试。", datainfo
        )


# ---- 测试 ----
if __name__ == "__main__":
    print("=== RAG桥接模块测试 ===\n")
    print(f"RAG地址: {RAG_API_URL}")
    print(f"用户名: {RAG_USERNAME}")
    print(f"角色: {RAG_ROLE_TYPE}")

    try:
        _ensure_initialized()
        print(f"登录成功, token={_token[:20]}..., conversation_id={_conversation_id}")

        # 测试流式聊天
        print("\n--- 测试提问 ---")
        payload = json.dumps({
            "conversation_id": _conversation_id,
            "message": "你好，请简单介绍一下自己",
            "stream": True,
        }).encode("utf-8")
        req = urllib_request.Request(
            f"{RAG_API_URL}/api/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        resp = urllib_request.urlopen(req, timeout=60)

        full_reply = ""
        buffer = ""
        for chunk in resp:
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    event = json.loads(data_str)
                    if event.get("type") == "delta":
                        t = event.get("delta", "")
                        full_reply += t
                        print(t, end="", flush=True)
                    elif event.get("type") == "done":
                        print("\n\n[DONE]")
                    elif event.get("type") == "status":
                        msg = event.get("message", "")
                        if msg:
                            print(f"\n[STATUS] {msg}")
                    elif event.get("type") == "error":
                        print(f"\n[ERROR] {event.get('message', '')}")
                except json.JSONDecodeError:
                    pass

        print(f"\n\n完整回复 ({len(full_reply)} 字符):")
        print(full_reply[:300])

    except Exception as e:
        print(f"错误: {e}")
