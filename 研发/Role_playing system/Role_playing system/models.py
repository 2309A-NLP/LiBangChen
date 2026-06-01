# -*- coding: utf-8 -*-
"""
数据模型与数据库初始化
======================
功能：定义所有 SQLAlchemy ORM 模型，管理数据库连接和会话。
支持 SQLite（默认）和 MySQL 两种后端。

模型列表：
  - User: 用户
  - Role: 角色
  - Conversation: 会话
  - Message: 消息
  - ChatRequestLog: 聊天请求日志
  - UploadedFile: 上传文件记录
  - UserDocumentChunk: 用户文档分块
  - KnowledgeDocument: 知识文档
"""

import re          # 正则表达式（用于验证数据库名）
from datetime import datetime  # 时间戳

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# 导入数据库配置
from config import DATABASE_BACKEND, DATABASE_URL, MYSQL_CONFIG, SQLITE_DATABASE_URL

# ============================================================
# 数据库后端检测
# ============================================================
EXPLICIT_DATABASE_URL = bool(DATABASE_URL)  # 是否显式指定了数据库 URL
USING_SQLITE = (
    (EXPLICIT_DATABASE_URL and DATABASE_URL.startswith("sqlite"))
    or (not EXPLICIT_DATABASE_URL and DATABASE_BACKEND == "sqlite")
)
USING_MYSQL = (
    (EXPLICIT_DATABASE_URL and DATABASE_URL.startswith("mysql"))
    or (not EXPLICIT_DATABASE_URL and DATABASE_BACKEND == "mysql")
)

# MySQL 需要 pymysql 驱动
if USING_MYSQL:
    import pymysql
    pymysql.install_as_MySQLdb()

# ORM 基类
Base = declarative_base()


# ============================================================
# 用户模型
# ============================================================
class User(Base):
    """用户表：存储用户账号信息。"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 用户 ID（主键）
    username = Column(String(50), unique=True, nullable=False)  # 用户名（唯一）
    password = Column(String(255), nullable=False)              # 密码哈希
    email = Column(String(100))                                 # 邮箱
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间
    is_active = Column(Boolean, default=True)                   # 是否激活

    conversations = relationship("Conversation", back_populates="user")  # 关联会话


# ============================================================
# 角色模型
# ============================================================
class Role(Base):
    """角色表：定义 AI 助手的角色类型。"""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 角色 ID（主键）
    role_type = Column(String(50), unique=True, nullable=False)  # 角色类型（如 lawyer, doctor）
    role_name = Column(String(100), nullable=False)             # 角色名称（如 王律师）
    description = Column(Text)                                  # 角色描述
    prompt_template = Column(Text)                              # Prompt 模板
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间

    conversations = relationship("Conversation", back_populates="role")  # 关联会话


# ============================================================
# 会话模型
# ============================================================
class Conversation(Base):
    """会话表：存储用户与 AI 助手的对话会话。"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 会话 ID（主键）
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 用户 ID（外键）
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)  # 角色 ID（外键）
    title = Column(String(200))                                 # 会话标题
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间

    user = relationship("User", back_populates="conversations")  # 关联用户
    role = relationship("Role", back_populates="conversations")  # 关联角色
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")  # 关联消息


# ============================================================
# 消息模型
# ============================================================
class Message(Base):
    """消息表：存储会话中的每条消息。"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 消息 ID（主键）
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)  # 会话 ID（外键）
    sender_type = Column(String(20), nullable=False)            # 发送者类型（user/assistant）
    content = Column(Text, nullable=False)                      # 消息内容
    created_at = Column(DateTime, default=datetime.now)         # 创建时间

    conversation = relationship("Conversation", back_populates="messages")  # 关联会话


# ============================================================
# 聊天请求日志模型
# ============================================================
class ChatRequestLog(Base):
    """聊天请求日志表：记录聊天请求的去重和状态。"""
    __tablename__ = "chat_request_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 日志 ID（主键）
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)  # 会话 ID（外键）
    client_request_id = Column(String(100), unique=True, nullable=False)  # 客户端请求 ID（唯一，用于去重）
    user_message = Column(Text)                                 # 用户消息
    reply = Column(Text)                                        # AI 回复
    status = Column(String(20), default="processing", nullable=False)  # 状态（processing/completed/failed）
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间


# ============================================================
# 上传文件模型
# ============================================================
class UploadedFile(Base):
    """上传文件表：记录用户上传的文件信息。"""
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 文件 ID（主键）
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 用户 ID（外键）
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)  # 会话 ID（外键）
    original_name = Column(String(255), nullable=False)         # 原始文件名
    stored_name = Column(String(255), nullable=False)           # 存储文件名
    file_ext = Column(String(20), nullable=False)               # 文件扩展名
    mime_type = Column(String(120))                             # MIME 类型
    size_bytes = Column(Integer, default=0)                     # 文件大小（字节）
    storage_path = Column(String(500), nullable=False)          # 存储路径
    parse_status = Column(String(20), default="ready", nullable=False)  # 解析状态
    parse_error = Column(Text)                                  # 解析错误信息
    text_length = Column(Integer, default=0)                    # 提取的文本长度
    chunk_count = Column(Integer, default=0)                    # 分块数量
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间


# ============================================================
# 用户文档分块模型
# ============================================================
class UserDocumentChunk(Base):
    """用户文档分块表：存储用户上传文件的分块内容。"""
    __tablename__ = "user_document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 分块 ID（主键）
    file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=False)  # 文件 ID（外键）
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 用户 ID（外键）
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)  # 会话 ID（外键）
    title = Column(String(500))                                 # 分块标题
    content = Column(Text, nullable=False)                      # 分块内容
    source = Column(String(255))                                # 来源
    chunk_index = Column(Integer, default=0)                    # 分块索引
    created_at = Column(DateTime, default=datetime.now)         # 创建时间


# ============================================================
# 知识文档模型
# ============================================================
class KnowledgeDocument(Base):
    """知识文档表：存储系统知识库文档。"""
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)  # 文档 ID（主键）
    title = Column(String(500))                                 # 文档标题
    content = Column(Text)                                      # 文档内容
    source = Column(String(200))                                # 文档来源
    role_type = Column(String(50))                              # 关联角色类型
    created_at = Column(DateTime, default=datetime.now)         # 创建时间
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # 更新时间


# ============================================================
# 数据库连接配置
# ============================================================
# MySQL 数据库 URL 构建
MYSQL_DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=MYSQL_CONFIG["user"],
    password=MYSQL_CONFIG["password"],
    host=MYSQL_CONFIG["host"],
    port=MYSQL_CONFIG["port"],
    database=MYSQL_CONFIG["database"],
    query={"charset": MYSQL_CONFIG["charset"]},
)

# MySQL 服务器 URL（不含数据库名，用于创建数据库）
SERVER_URL = URL.create(
    "mysql+pymysql",
    username=MYSQL_CONFIG["user"],
    password=MYSQL_CONFIG["password"],
    host=MYSQL_CONFIG["host"],
    port=MYSQL_CONFIG["port"],
    query={"charset": MYSQL_CONFIG["charset"]},
)

# 最终使用的数据库 URL
if EXPLICIT_DATABASE_URL:
    EFFECTIVE_DATABASE_URL = DATABASE_URL
elif DATABASE_BACKEND == "mysql":
    EFFECTIVE_DATABASE_URL = MYSQL_DATABASE_URL
else:
    EFFECTIVE_DATABASE_URL = SQLITE_DATABASE_URL

# 创建数据库引擎
if USING_SQLITE:
    # SQLite：需要 check_same_thread=False 以支持多线程访问
    engine = create_engine(EFFECTIVE_DATABASE_URL, connect_args={"check_same_thread": False})
elif USING_MYSQL:
    # MySQL：启用连接池心跳检测
    engine = create_engine(
        EFFECTIVE_DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
else:
    engine = create_engine(EFFECTIVE_DATABASE_URL, pool_pre_ping=True)

# 数据库会话工厂
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_database():
    """
    初始化数据库：创建所有 ORM 表。
    
    对于 MySQL，会自动创建数据库（如果不存在）。
    对于 SQLite，直接创建表。
    """
    if not USING_MYSQL:
        # SQLite：直接创建所有表
        Base.metadata.create_all(engine)
        return

    # MySQL：先创建数据库，再创建表
    database_name = MYSQL_CONFIG["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError(f"Invalid database name: {database_name}")

    # 连接到 MySQL 服务器（不指定数据库）
    server_engine = create_engine(
        SERVER_URL,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with server_engine.connect() as conn:
            # 创建数据库（如果不存在）
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "DEFAULT CHARACTER SET utf8mb4 "
                    "DEFAULT COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()

    # 创建所有表
    Base.metadata.create_all(engine)
