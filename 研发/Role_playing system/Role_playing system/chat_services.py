# -*- coding: utf-8 -*-
"""聊天业务服务层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from models import ChatRequestLog, Conversation, KnowledgeDocument, Message, Role, User
from security import hash_password, verify_password
from chat_exceptions import DuplicateUsernameError


class UserService:
    def __init__(self, db):
        self.db = db

    def normalize_username(self, username: str) -> str:
        normalized = (username or "").strip()
        if not normalized:
            raise ValueError("用户名不能为空。")
        return normalized

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username).first()

    def create_user(self, username: str, password: str, email: str = None) -> User:
        normalized_username = self.normalize_username(username)
        if self.get_user_by_username(normalized_username):
            raise DuplicateUsernameError("账号重复，请更换用户名。")
        user = User(username=normalized_username, password=hash_password(password), email=email)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate_user(self, username: str, password: str) -> User:
        normalized_username = self.normalize_username(username)
        user = self.db.query(User).filter(User.username == normalized_username, User.is_active.is_(True)).first()
        if not user or not verify_password(password, user.password):
            raise ValueError("用户名或密码错误。")
        return user

    def get_active_user(self, user_id: int) -> User:
        user = self.db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not user:
            raise ValueError("当前用户不存在或已被禁用。")
        return user


class RoleService:
    def __init__(self, db):
        self.db = db

    def get_or_create_role(self, role_type: str) -> Role:
        role = self.db.query(Role).filter(Role.role_type == role_type).first()
        if role:
            return role
        from config import ROLES
        role_info = ROLES.get(role_type)
        if not role_info:
            raise ValueError(f"不支持的角色类型：{role_type}")
        role = Role(role_type=role_type, role_name=role_info.get("name", ""), description=role_info.get("description", ""))
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role


class ConversationService:
    PLACEHOLDER_TITLES = {"新对话", "未命名对话"}

    def __init__(self, db):
        self.db = db

    def create_conversation(self, user_id: int, role_type: str, title: str = None) -> Conversation:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"用户不存在：{user_id}")
        role = RoleService(self.db).get_or_create_role(role_type)
        conversation = Conversation(user_id=user_id, role_id=role.id, title=(title or "").strip() or "新对话")
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def get_conversation(self, conversation_id: int) -> Optional[Conversation]:
        return self.db.query(Conversation).filter(Conversation.id == conversation_id).first()

    def get_owned_conversation(self, user_id: int, conversation_id: int) -> Conversation:
        conversation = self.db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if not conversation:
            raise ValueError("当前会话不存在，或不属于当前用户。")
        return conversation

    def rename_conversation(self, conversation_id: int, title: str, user_id: Optional[int] = None) -> Conversation:
        conversation = self.get_owned_conversation(user_id, conversation_id) if user_id is not None else self.get_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"会话不存在：{conversation_id}")
        normalized_title = (title or "").strip()
        if not normalized_title:
            raise ValueError("会话标题不能为空。")
        conversation.title = normalized_title
        conversation.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def delete_conversation(self, conversation_id: int, user_id: Optional[int] = None) -> None:
        conversation = self.get_owned_conversation(user_id, conversation_id) if user_id is not None else self.get_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"会话不存在：{conversation_id}")
        self.db.query(Message).filter(Message.conversation_id == conversation_id).delete(synchronize_session=False)
        self.db.query(ChatRequestLog).filter(ChatRequestLog.conversation_id == conversation_id).delete(synchronize_session=False)
        self.db.delete(conversation)
        self.db.commit()


