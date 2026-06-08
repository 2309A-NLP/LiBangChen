"""会话存储模块。

定义会话消息存储的抽象基类和两种实现：内存存储（单机）和 Redis 存储（分布式）。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from threading import Lock
from typing import Any
import uuid

from app.schemas.query import SessionMessage


class BaseSessionStore:
    """会话存储抽象基类，定义消息追加和读取接口。"""
    def create_session_id(self) -> str:
        return uuid.uuid4().hex

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        raise NotImplementedError

    def get_messages(self, session_id: str) -> list[SessionMessage]:
        raise NotImplementedError


class InMemorySessionStore(BaseSessionStore):
    """基于内存字典的会话存储，适用于单机部署。线程安全。"""
    def __init__(self) -> None:
        self._store: dict[str, list[SessionMessage]] = {}
        self._lock = Lock()

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        message = SessionMessage(
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        with self._lock:
            self._store.setdefault(session_id, []).append(message)
        return message

    def get_messages(self, session_id: str) -> list[SessionMessage]:
        with self._lock:
            return list(self._store.get(session_id, []))


class RedisSessionStore(BaseSessionStore):
    """基于 Redis 的会话存储，适用于多实例分布式部署，支持 TTL 自动过期。"""
    def __init__(self, redis_url: str, key_prefix: str, ttl_seconds: int) -> None:
        """初始化 Redis 存储，传入连接地址、键前缀和过期时间。"""
        from redis import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix
        self._ttl_seconds = ttl_seconds

    def ping(self) -> None:
        self._redis.ping()

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        message = SessionMessage(
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        key = self._key(session_id)
        self._redis.rpush(key, message.model_dump_json())
        self._redis.expire(key, self._ttl_seconds)
        return message

    def get_messages(self, session_id: str) -> list[SessionMessage]:
        key = self._key(session_id)
        entries = self._redis.lrange(key, 0, -1)
        messages: list[SessionMessage] = []
        for raw in entries:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                messages.append(SessionMessage(**payload))
            except TypeError:
                continue
        return messages

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"
