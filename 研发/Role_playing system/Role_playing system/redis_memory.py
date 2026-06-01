# -*- coding: utf-8 -*-
"""
短期对话记忆模块
功能：基于 Redis 的短期对话记忆，支持多轮对话的消息持久化和上下文压缩。
当 Redis 不可用时，自动降级到进程内内存存储。

主要类：RedisMemory
  - add_message(): 添加消息到对话历史
  - get_recent_messages(): 获取最近 N 条消息
  - get_all_messages(): 获取全部消息
  - clear_conversation(): 清除对话记忆
  - update_conversation_context(): 更新对话上下文
  - get_conversation_context(): 获取对话上下文
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

import redis
from redis.exceptions import RedisError

from config import REDIS_CONFIG, SHORT_TERM_MEMORY_CONFIG


class RedisMemory:
    """
    短期对话记忆类。
    
    基于 Redis 实现多轮对话的消息持久化，支持自动过期和消息数量限制。
    当 Redis 不可用时，自动降级到进程内内存存储（类级别共享）。
    """

    _message_fallback_store: Dict[str, List[str]] = {}
    _context_fallback_store: Dict[str, str] = {}

    def __init__(self):
        """初始化 Redis 连接和配置参数。"""
        self.client = redis.Redis(
            host=REDIS_CONFIG["host"],
            port=REDIS_CONFIG["port"],
            password=REDIS_CONFIG["password"],
            db=REDIS_CONFIG["db"],
            decode_responses=True,
        )
        self.max_messages = SHORT_TERM_MEMORY_CONFIG["max_messages"]
        self.expire_time = SHORT_TERM_MEMORY_CONFIG["expire_time"]
        self.available = self._ping()

    def _ping(self) -> bool:
        """
        测试 Redis 连接是否可用。
        
        Returns:
            bool: True 表示连接正常
        """
        try:
            self.client.ping()
            return True
        except RedisError:
            return False

    def _get_conversation_key(self, conversation_id: int) -> str:
        """
        获取对话在 Redis 中的存储键。
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            str: Redis 键名（格式：conversation:{id}:messages）
        """
        return f"conversation:{conversation_id}:messages"

    def add_message(self, conversation_id: int, sender_type: str, content: str):
        """
        添加消息到对话历史。
        
        自动限制消息数量（保留最近 N 条）并设置过期时间。
        Redis 不可用时降级到内存存储。
        
        Args:
            conversation_id: 会话 ID
            sender_type: 发送者类型（user/assistant）
            content: 消息内容
        """
        key = self._get_conversation_key(conversation_id)
        message = {
            "sender_type": sender_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        encoded = json.dumps(message, ensure_ascii=False)

        if self.available:
            try:
                self.client.rpush(key, encoded)
                self.client.ltrim(key, -self.max_messages, -1)
                self.client.expire(key, self.expire_time)
                return
            except RedisError:
                self.available = False

        messages = self._message_fallback_store.setdefault(key, [])
        messages.append(encoded)
        self._message_fallback_store[key] = messages[-self.max_messages :]

    def get_recent_messages(self, conversation_id: int, limit: int = 10) -> List[Dict]:
        """
        获取最近 N 条消息。
        
        Args:
            conversation_id: 会话 ID
            limit: 返回消息条数上限，默认 10
            
        Returns:
            List[Dict]: 消息列表 [{sender_type, content, timestamp}]
        """
        key = self._get_conversation_key(conversation_id)

        if self.available:
            try:
                messages = self.client.lrange(key, -limit, -1)
                return [json.loads(msg) for msg in messages]
            except RedisError:
                self.available = False

        messages = self._message_fallback_store.get(key, [])[-limit:]
        return [json.loads(msg) for msg in messages]

    def get_all_messages(self, conversation_id: int) -> List[Dict]:
        """
        获取对话的全部消息。
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            List[Dict]: 全部消息列表
        """
        key = self._get_conversation_key(conversation_id)

        if self.available:
            try:
                messages = self.client.lrange(key, 0, -1)
                return [json.loads(msg) for msg in messages]
            except RedisError:
                self.available = False

        return [json.loads(msg) for msg in self._message_fallback_store.get(key, [])]

    def clear_conversation(self, conversation_id: int):
        """
        清除对话的记忆（消息和上下文）。
        
        Args:
            conversation_id: 会话 ID
        """
        key = self._get_conversation_key(conversation_id)

        if self.available:
            try:
                self.client.delete(key)
            except RedisError:
                self.available = False

        self._message_fallback_store.pop(key, None)
        self._context_fallback_store.pop(f"conversation:{conversation_id}:context", None)

    def update_conversation_context(self, conversation_id: int, context: Dict):
        """
        更新对话的压缩上下文。
        
        Args:
            conversation_id: 会话 ID
            context: 上下文字典
        """
        key = f"conversation:{conversation_id}:context"
        encoded = json.dumps(context, ensure_ascii=False)

        if self.available:
            try:
                self.client.setex(key, self.expire_time, encoded)
                return
            except RedisError:
                self.available = False

        self._context_fallback_store[key] = encoded

    def get_conversation_context(self, conversation_id: int) -> Optional[Dict]:
        """
        获取对话的压缩上下文。
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            Optional[Dict]: 上下文字典，不存在返回 None
        """
        key = f"conversation:{conversation_id}:context"

        if self.available:
            try:
                context = self.client.get(key)
                return json.loads(context) if context else None
            except RedisError:
                self.available = False

        context = self._context_fallback_store.get(key)
        return json.loads(context) if context else None
