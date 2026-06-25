"""会话服务模块。

提供会话管理和对话历史的高层接口，封装底层 session store 的操作。
"""
from __future__ import annotations

from typing import Any

from app.schemas.query import SessionMessage
from app.services.session_store import BaseSessionStore


class SessionService:
    """会话服务，管理会话生命周期和消息存取。"""
    def __init__(self, store: BaseSessionStore) -> None:
        """初始化会话服务，注入底层存储实现。"""
        self.store = store

    def ensure_session_id(self, session_id: str | None) -> str:
        """确保返回有效的会话 ID，未传入时自动创建。"""
        if session_id:
            return session_id
        return self.store.create_session_id()

    def add_user_message(
        self,
        session_id: str,
        question: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        return self.store.append_message(session_id, "user", question, metadata)

    def add_assistant_message(
        self,
        session_id: str,
        answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        return self.store.append_message(session_id, "assistant", answer, metadata)

    def get_history(self, session_id: str) -> list[SessionMessage]:
        return self.store.get_messages(session_id)

    def build_context_messages(self, session_id: str, limit: int = 8) -> list[dict[str, str]]:
        """构建用于 LLM 的上下文消息列表，截取最近 limit 条。"""
        history = self.get_history(session_id)
        if limit > 0:
            history = history[-limit:]
        return [{"role": item.role, "content": item.content} for item in history if item.content]
