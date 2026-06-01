# -*- coding: utf-8 -*-
"""核心聊天服务。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterator, Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from chat_exceptions import DuplicateUsernameError
from chat_services import ConversationService, RoleService, UserService
from file_service import UserFileService
from logging_utils import get_logger
from models import ChatRequestLog, Conversation, KnowledgeDocument, Message, Role, SessionLocal
from data_processor import DataProcessor

if TYPE_CHECKING:
    from rag_chain import RAGChain

logger = get_logger(__name__)


class ChatBot:
    PLACEHOLDER_TITLES = {"新对话", "未命名对话"}

    def __init__(self):
        self.db = SessionLocal()
        self.user_service = UserService(self.db)
        self.role_service = RoleService(self.db)
        self.conversation_service = ConversationService(self.db)
        self._rag_chain: Any = None

    @property
    def rag_chain(self) -> "RAGChain":
        if self._rag_chain is None:
            from rag_chain import RAGChain
            self._rag_chain = RAGChain()
        return self._rag_chain

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            error_text = str(exc).lower()
            if "users.username" in error_text or "duplicate" in error_text or "unique constraint failed: users.username" in error_text:
                raise DuplicateUsernameError("账号重复，请更换用户名。") from exc
            raise ValueError("数据库约束校验失败。") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RuntimeError("数据库操作失败，请稍后重试。") from exc

    def create_user(self, username: str, password: str, email: str = None):
        return self.user_service.create_user(username, password, email)

    def authenticate_user(self, username: str, password: str):
        return self.user_service.authenticate_user(username, password)

    def get_active_user(self, user_id: int):
        return self.user_service.get_active_user(user_id)

    def create_conversation(self, user_id: int, role_type: str, title: str = None):
        return self.conversation_service.create_conversation(user_id, role_type, title)

    def get_or_create_role(self, role_type: str):
        return self.role_service.get_or_create_role(role_type)

    def get_conversation(self, conversation_id: int):
        return self.conversation_service.get_conversation(conversation_id)

    def get_owned_conversation(self, user_id: int, conversation_id: int):
        return self.conversation_service.get_owned_conversation(user_id, conversation_id)

    def rename_conversation(self, conversation_id: int, title: str, user_id: Optional[int] = None):
        return self.conversation_service.rename_conversation(conversation_id, title, user_id=user_id)

    def delete_conversation(self, conversation_id: int, user_id: Optional[int] = None) -> None:
        self.conversation_service.delete_conversation(conversation_id, user_id=user_id)
        if self._rag_chain is not None:
            self._rag_chain.memory.clear_conversation(conversation_id)

    def save_message_pair(self, conversation_id: int, user_message: str, assistant_message: str) -> None:
        self.db.add_all([
            Message(conversation_id=conversation_id, sender_type="user", content=user_message),
            Message(conversation_id=conversation_id, sender_type="assistant", content=assistant_message),
        ])
        conversation = self.get_conversation(conversation_id)
        if conversation:
            conversation.updated_at = datetime.now()
        self._commit()

    def _get_request_log(self, client_request_id: Optional[str]):
        if not client_request_id:
            return None
        return self.db.query(ChatRequestLog).filter(ChatRequestLog.client_request_id == client_request_id).first()

    def _create_request_log(self, conversation_id: int, client_request_id: str, user_message: str):
        request_log = ChatRequestLog(
            conversation_id=conversation_id,
            client_request_id=client_request_id,
            user_message=user_message,
            status="processing",
        )
        self.db.add(request_log)
        self._commit()
        self.db.refresh(request_log)
        return request_log

    def _get_conversation_and_role(self, conversation_id: int, user_id: Optional[int] = None):
        conversation = self.get_owned_conversation(user_id, conversation_id) if user_id is not None else self.get_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"会话不存在：{conversation_id}")
        role = self.db.query(Role).filter(Role.id == conversation.role_id).first()
        if not role:
            raise ValueError(f"会话角色不存在：{conversation.role_id}")
        return conversation, role

    def _handle_request_log(self, client_request_id: Optional[str], conversation_id: int, user_message: str):
        request_log = self._get_request_log(client_request_id)
        if request_log and request_log.status == "completed" and request_log.reply:
            return request_log, {"reply": request_log.reply, "meta": {"request_reused": True}}
        if request_log and request_log.status == "processing":
            raise ValueError("相同请求正在处理中，请稍后再试。")
        if client_request_id and not request_log:
            request_log = self._create_request_log(conversation_id, client_request_id, user_message)
        return request_log, None

    def _build_history_messages(self, conversation_id: int, limit: int = 6):
        return self.rag_chain.memory.get_recent_messages(conversation_id, limit=limit)

    def chat(self, conversation_id: int, user_message: str, client_request_id: Optional[str] = None, user_id: Optional[int] = None) -> dict:
        conversation, role = self._get_conversation_and_role(conversation_id, user_id=user_id)
        request_log, reused = self._handle_request_log(client_request_id, conversation_id, user_message)
        if reused is not None:
            return reused
        history_messages = self._build_history_messages(conversation_id, limit=6)
        try:
            reply = self.rag_chain.generate_response(
                conversation_id=conversation_id,
                user_message=user_message,
                role_type=role.role_type,
                role_name=role.role_name,
                role_description=role.description,
                user_id=conversation.user_id,
                history_messages=history_messages,
            )
            self.save_message_pair(conversation_id, user_message, reply)
            if request_log:
                request_log.reply = reply
                request_log.status = "completed"
                request_log.updated_at = datetime.now()
                self._commit()
            return {"reply": reply, "meta": dict(getattr(self.rag_chain, "last_run_meta", {}) or {})}
        except Exception:
            if request_log:
                request_log.status = "failed"
                request_log.updated_at = datetime.now()
                self._commit()
            raise

    def stream_chat(self, conversation_id: int, user_message: str, client_request_id: Optional[str] = None, user_id: Optional[int] = None) -> Iterator[dict]:
        conversation, role = self._get_conversation_and_role(conversation_id, user_id=user_id)
        request_log, reused = self._handle_request_log(client_request_id, conversation_id, user_message)
        if reused is not None:
            yield {"type": "reused", "delta": reused["reply"], "reply": reused["reply"], "meta": reused["meta"]}
            return
        history_messages = self._build_history_messages(conversation_id, limit=6)
        chunks: list[str] = []
        try:
            for chunk in self.rag_chain.stream_response(
                conversation_id=conversation_id,
                user_message=user_message,
                role_type=role.role_type,
                role_name=role.role_name,
                role_description=role.description,
                user_id=conversation.user_id,
                history_messages=history_messages,
            ):
                if isinstance(chunk, dict):
                    if chunk.get("type") == "status":
                        yield {"type": "status", "stage": chunk.get("stage"), "message": chunk.get("message")}
                        continue
                if chunk:
                    chunks.append(chunk)
                    yield {"type": "delta", "delta": chunk}
            reply = self.rag_chain._normalize_output_format("".join(chunks).strip())
            self.rag_chain.memory.add_message(conversation_id, "user", user_message)
            self.rag_chain.memory.add_message(conversation_id, "assistant", reply)
            self.save_message_pair(conversation_id, user_message, reply)
            if request_log:
                request_log.reply = reply
                request_log.status = "completed"
                request_log.updated_at = datetime.now()
                self._commit()
            yield {
                "type": "done",
                "reply": reply,
                "meta": dict(getattr(self.rag_chain, "last_run_meta", {}) or {}),
                "search_meta": dict(getattr(self.rag_chain.vector_store, "last_search_meta", {}) or {}),
            }
        except Exception:
            if request_log:
                request_log.status = "failed"
                request_log.updated_at = datetime.now()
                self._commit()
            raise

    def get_conversation_history(self, conversation_id: int, limit: int = 20, user_id: Optional[int] = None) -> list:
        if user_id is not None:
            self.get_owned_conversation(user_id, conversation_id)
        messages = (
            self.db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
            .all()
        )
        if messages:
            messages.reverse()
            return [{"sender_type": msg.sender_type, "content": msg.content, "time": msg.created_at} for msg in messages]
        redis_messages = self.rag_chain.memory.get_recent_messages(conversation_id, limit)
        return [{"sender_type": msg.get("sender_type"), "content": msg.get("content"), "time": msg.get("timestamp")} for msg in redis_messages]

    def add_knowledge_document(self, title: str, content: str, source: str, role_type: str, update_vector: bool = True) -> bool:
        processor = DataProcessor()
        normalized_title = processor.clean_text(title)
        normalized_content = processor.clean_text(content)
        normalized_source = processor.clean_text(source)
        existing = self.db.query(KnowledgeDocument).filter(KnowledgeDocument.role_type == role_type, KnowledgeDocument.title == title).first()
        if existing:
            if processor.clean_text(existing.content or "") == normalized_content and processor.clean_text(existing.source or "") == normalized_source:
                return False
            existing.content = content
            existing.source = source
            existing.updated_at = datetime.now()
            self._commit()
            if update_vector:
                self.rag_chain.update_knowledge_base([processor.process_document({"title": title, "content": content, "source": source, "role_type": role_type})])
            return True
        doc = KnowledgeDocument(title=normalized_title or title, content=normalized_content or content, source=normalized_source or source, role_type=role_type)
        self.db.add(doc)
        self._commit()
        if update_vector:
            self.rag_chain.update_knowledge_base([processor.process_document({"title": normalized_title or title, "content": normalized_content or content, "source": normalized_source or source, "role_type": role_type})])
        return True

    def get_user_conversations(self, user_id: int) -> list:
        conversations = self.db.query(Conversation).filter(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).all()
        result = []
        for conv in conversations:
            role = self.db.query(Role).filter(Role.id == conv.role_id).first()
            result.append({"id": conv.id, "title": conv.title, "role_type": role.role_type if role else None, "role_name": role.role_name if role else None, "created_at": conv.created_at, "updated_at": conv.updated_at})
        return result

    def list_conversation_files(self, user_id: int, conversation_id: int) -> list:
        return UserFileService(self.db).list_conversation_files(user_id, conversation_id)

    def upload_conversation_file(self, user_id: int, conversation_id: int, filename: str, content_type: str, file_bytes: bytes) -> dict:
        uploaded_file = UserFileService(self.db).upload_file(user_id=user_id, conversation_id=conversation_id, filename=filename, content_type=content_type, file_bytes=file_bytes)
        return UserFileService(self.db).serialize_file(uploaded_file)

    def analyze_file_role(self, filename: str, file_bytes: bytes) -> dict:
        return UserFileService(self.db).analyze_file_role(filename, file_bytes)

    def delete_uploaded_file(self, user_id: int, file_id: int) -> None:
        UserFileService(self.db).delete_uploaded_file(user_id, file_id)

    def close(self) -> None:
        self.db.close()
