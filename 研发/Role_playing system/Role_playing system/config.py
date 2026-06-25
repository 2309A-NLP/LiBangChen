# -*- coding: utf-8 -*-
"""
配置中心
========
功能：集中管理所有模块的配置参数，从环境变量和 .env 文件加载。
所有配置项都有默认值，可直接启动无需额外配置。

配置模块：
  - DATABASE: 数据库连接（SQLite/MySQL）
  - REDIS: Redis 缓存连接
  - MILVUS: Milvus 向量数据库连接
  - LLM: 大模型配置（模型名称、API Key、API Base）
  - ROLES: 7 种角色定义
  - APP: 应用服务器配置
  - AUTH: 认证安全配置
  - UPLOAD: 文件上传配置
  - KNOWLEDGE: 知识库同步配置
  - RETRIEVAL: 检索模式配置
  - RERANK: 重排序配置
"""

import os  # 操作系统接口（环境变量读取、路径操作）

from dotenv import load_dotenv  # 从 .env 文件加载环境变量

# ============================================================
# 基础路径设置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 项目根目录
load_dotenv(os.path.join(BASE_DIR, ".env"))  # 加载 .env 文件中的环境变量


def _resolve_project_path(path_value: str) -> str:
    """
    解析项目相对路径为绝对路径。
    
    如果路径是相对路径，则基于项目根目录（BASE_DIR）解析。
    
    Args:
        path_value: 路径值（相对或绝对）
        
    Returns:
        str: 解析后的绝对路径
    """
    value = (path_value or "").strip()
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(BASE_DIR, value))


def _get_bool_env(name: str, default: bool) -> bool:
    """
    读取布尔类型的环境变量。
    
    支持的值：1, true, yes, on（不区分大小写）
    
    Args:
        name: 环境变量名
        default: 默认值
        
    Returns:
        bool: 解析后的布尔值
    """
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int) -> int:
    """
    读取整数类型的环境变量。
    
    Args:
        name: 环境变量名
        default: 默认值
        
    Returns:
        int: 解析后的整数值，解析失败返回默认值
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    """
    读取浮点数类型的环境变量。
    
    Args:
        name: 环境变量名
        default: 默认值
        
    Returns:
        float: 解析后的浮点数值，解析失败返回默认值
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_csv_env(name: str, default: str = "") -> list[str]:
    """
    读取逗号分隔的环境变量为列表。
    
    Args:
        name: 环境变量名
        default: 默认值
        
    Returns:
        list[str]: 解析后的字符串列表
    """
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# ============================================================
# 数据库配置
# ============================================================
# 默认使用 SQLite，适合直接在本地或轻量环境启动。
# 如需切换到 MySQL：
# 1. 设置 DATABASE_BACKEND=mysql 并填写 MYSQL_* 配置，或
# 2. 直接设置 DATABASE_URL=mysql+pymysql://...
DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower() or "sqlite"
if DATABASE_BACKEND not in {"sqlite", "mysql"}:
    DATABASE_BACKEND = "sqlite"

# SQLite 数据库文件路径
_sqlite_database_url = os.getenv("SQLITE_DATABASE_URL", "sqlite:///./roleplay_system.db").strip()
if _sqlite_database_url.startswith("sqlite:///./"):
    SQLITE_DATABASE_URL = f"sqlite:///{_resolve_project_path(_sqlite_database_url[len('sqlite:///./'):])}"
else:
    SQLITE_DATABASE_URL = _sqlite_database_url
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()  # 自定义数据库 URL（覆盖 SQLite/MySQL 配置）

# MySQL 连接配置
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),       # MySQL 主机地址
    "port": int(os.getenv("MYSQL_PORT", 3306)),         # MySQL 端口
    "user": os.getenv("MYSQL_USER", "root"),            # MySQL 用户名
    "password": os.getenv("MYSQL_PASSWORD", "123456"),  # MySQL 密码
    "database": os.getenv("MYSQL_DB", "roleplay_system"),  # MySQL 数据库名
    "charset": "utf8mb4",                               # 字符集
}

# ============================================================
# Redis 缓存配置
# ============================================================
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "localhost"),   # Redis 主机地址
    "port": int(os.getenv("REDIS_PORT", 6379)),     # Redis 端口
    "password": os.getenv("REDIS_PASSWORD", None),  # Redis 密码（可选）
    "db": int(os.getenv("REDIS_DB", 0)),            # Redis 数据库编号
}

# ============================================================
# Milvus 向量数据库配置
# ============================================================
MILVUS_CONFIG = {
    "enabled": _get_bool_env("ENABLE_MILVUS", False),           # 是否启用 Milvus
    "uri": os.getenv("MILVUS_URI", "").strip(),                 # Milvus URI（替代 host:port）
    "host": os.getenv("MILVUS_HOST", "localhost").strip(),      # Milvus 主机地址
    "port": int(os.getenv("MILVUS_PORT", 19530)),               # Milvus 端口
    "collection_name": os.getenv("MILVUS_COLLECTION_NAME", "knowledge_base"),  # 知识库集合名
    "user_collection_name": os.getenv("MILVUS_USER_COLLECTION_NAME", "user_documents"),  # 用户文档集合名
    "user": os.getenv("MILVUS_USER", "").strip(),               # Milvus 用户名
    "password": os.getenv("MILVUS_PASSWORD", "").strip(),       # Milvus 密码
    "token": os.getenv("MILVUS_TOKEN", "").strip(),             # Milvus 令牌
    "db_name": os.getenv("MILVUS_DB_NAME", "").strip(),         # Milvus 数据库名
    "secure": _get_bool_env("MILVUS_SECURE", False),            # 是否启用 TLS
    "timeout": _get_float_env("MILVUS_TIMEOUT", 10.0),          # 连接超时（秒）
}

# ============================================================
# 低内存模式配置
# ============================================================
LOW_MEMORY_MODE_CONFIG = {
    "enabled": _get_bool_env("LOW_MEMORY_MODE", False),  # 低内存模式开关
}

# ============================================================
# 混合检索配置
# ============================================================
HYBRID_RETRIEVAL_CONFIG = {
    "enabled": _get_bool_env("ENABLE_HYBRID_RETRIEVAL", True),  # 混合检索开关
    "rrf_k": max(_get_int_env("HYBRID_RRF_K", 60), 1),          # RRF 融合参数 k
    "candidate_multiplier": max(
        _get_int_env("HYBRID_CANDIDATE_MULTIPLIER", 1 if LOW_MEMORY_MODE_CONFIG["enabled"] else 2),
        1,
    ),  # 候选文档倍数
    "bm25_k1": _get_float_env("BM25_K1", 1.5),     # BM25 参数 k1
    "bm25_b": _get_float_env("BM25_B", 0.75),      # BM25 参数 b
    "milvus_reconnect_interval_seconds": max(_get_int_env("MILVUS_RECONNECT_INTERVAL_SECONDS", 120), 5),  # Milvus 重连间隔
    "mode": os.getenv("RETRIEVAL_MODE", "hybrid_rerank").strip().lower() or "hybrid_rerank",  # 检索模式
}

# ============================================================
# 重排序配置
# ============================================================
RERANK_CONFIG = {
    "enabled": _get_bool_env("ENABLE_RERANK", not LOW_MEMORY_MODE_CONFIG["enabled"]),  # 重排序开关
    "model_path": os.getenv(
        "RERANK_MODEL_PATH",
        os.path.join(BASE_DIR, "models", "bge-reranker-base"),
    ).strip(),  # BGE-Reranker 模型路径
    "candidate_limit": max(
        _get_int_env("RERANK_CANDIDATE_LIMIT", 4 if LOW_MEMORY_MODE_CONFIG["enabled"] else 8),
        2,
    ),  # 重排序候选文档数量限制
}

# ============================================================
# LLM 配置
# ============================================================
LLM_CONFIG = {
    "model_name": os.getenv("LLM_MODEL", "gpt-4o-mini"),          # 模型名称
    "api_key": os.getenv("OPENAI_API_KEY", "your-api-key"),       # API Key
    "api_base": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),  # API 地址
    "temperature": float(os.getenv("LLM_TEMPERATURE", 0.7)),     # 生成温度
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", 4000)),        # 最大 Token 数
}

# ============================================================
# 角色定义
# ============================================================
ROLES = {
    "lawyer": {
        "name": "王律师",
        "description": "资深法律顾问，精通民商法、刑法，擅长结合法律条文解答问题。",
        "data_sources": [],
        "personality": "严谨、直接、克制，先给结论，再给法律分析。",
    },
    "stock_analyst": {
        "name": "张分析师",
        "description": "证券投资专家，精通技术分析和基本面分析，熟悉 A 股市场。",
        "data_sources": [],
        "personality": "冷静、理性、审慎，重视风险提示，说话像真实分析师。",
    },
    "teacher": {
        "name": "李老师",
        "description": "资深教师，擅长各学科知识讲解，耐心细致，循循善诱。",
        "data_sources": [],
        "personality": "耐心、温和、有条理，善于把复杂问题讲清楚。",
    },
    "psychological_counselor": {
        "name": "心理咨询师",
        "description": "侧重情绪疏导、压力管理、睡眠支持与心理求助建议，回答风格支持性强、清晰务实。",
        "data_sources": [],
        "personality": "共情、稳定、不评判，会先接住情绪，再给建议。",
    },
    "doctor": {
        "name": "陈医生",
        "description": "侧重常见症状初步判断、就医建议、体检指标基础解读、慢病管理与健康生活方式指导，强调不能替代线下面诊。",
        "data_sources": [],
        "personality": "专业、稳重、有分寸，以安全和就医建议为优先。",
    },
    "scientist": {
        "name": "周科学家",
        "description": "擅长用科研思维解释科学概念、实验设计、证据强度、论文阅读与科学新闻辨析，强调证据链和可重复性。",
        "data_sources": [],
        "personality": "求真、审慎、讲证据，不会把猜测当成结论。",
    },
    "custom_persona": {
        "name": "全能型人格",
        "description": "全能型在线问答助手，不强制依赖本地知识库，适合无法匹配固定角色的文件和问题。",
        "data_sources": [],
        "personality": "灵活、自然、兼顾效率，优先理解用户当下的目标。",
    },
}

# ============================================================
# 短期记忆配置
# ============================================================
SHORT_TERM_MEMORY_CONFIG = {
    "max_messages": 20,      # 最大保留消息数
    "expire_time": 3600,     # 过期时间（秒）
}

# ============================================================
# 应用服务器配置
# ============================================================
APP_CONFIG = {
    "host": os.getenv("APP_HOST", "127.0.0.1"),         # 监听地址（默认仅本机访问；如需局域网/公网请显式设置 0.0.0.0）
    "port": _get_int_env("APP_PORT", 8000),             # 监听端口
    "reload": _get_bool_env("APP_RELOAD", False),       # 热重载开关
    "cors_origins": _get_csv_env("APP_CORS_ORIGINS"),   # CORS 允许的源
    "trusted_hosts": _get_csv_env("APP_TRUSTED_HOSTS", "*"),  # 受信任的主机
}

# ============================================================
# 公网访问配置
# ============================================================
PUBLIC_ACCESS_CONFIG = {
    "base_url": os.getenv("PUBLIC_BASE_URL", "").strip(),               # 公网基础 URL
    "cloudflare_tunnel_token": os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "").strip(),  # Cloudflare Tunnel Token
}

# ============================================================
# 认证配置
# ============================================================
AUTH_CONFIG = {
    "secret_key": os.getenv("AUTH_SECRET_KEY", "").strip(),         # JWT 签名密钥
    "token_expire_hours": max(_get_int_env("AUTH_TOKEN_EXPIRE_HOURS", 168), 1),  # Token 过期时间（小时）
    "admin_api_key": os.getenv("ADMIN_API_KEY", "").strip(),        # 管理员 API Key
}

# ============================================================
# 安全配置（速率限制）
# ============================================================
SECURITY_CONFIG = {
    "login_rate_limit_per_minute": max(_get_int_env("LOGIN_RATE_LIMIT_PER_MINUTE", 20), 1),      # 登录频率限制
    "register_rate_limit_per_hour": max(_get_int_env("REGISTER_RATE_LIMIT_PER_HOUR", 10), 1),    # 注册频率限制
    "chat_rate_limit_per_minute": max(_get_int_env("CHAT_RATE_LIMIT_PER_MINUTE", 30), 1),        # 聊天频率限制
    "chat_ip_rate_limit_per_minute": max(_get_int_env("CHAT_IP_RATE_LIMIT_PER_MINUTE", 60), 1),  # 聊天 IP 频率限制
    "upload_rate_limit_per_minute": max(_get_int_env("UPLOAD_RATE_LIMIT_PER_MINUTE", 20), 1),    # 上传频率限制
    "analyze_rate_limit_per_minute": max(_get_int_env("ANALYZE_RATE_LIMIT_PER_MINUTE", 20), 1),  # 分析频率限制
}

# ============================================================
# 知识同步配置
# ============================================================
KNOWLEDGE_SYNC_CONFIG = {
    "enabled": _get_bool_env("KNOWLEDGE_SYNC_ENABLED", True),              # 知识同步开关
    "interval_minutes": max(_get_int_env("KNOWLEDGE_SYNC_INTERVAL_MINUTES", 10080), 1),  # 同步间隔（分钟，默认 7 天）
    "run_on_startup": _get_bool_env("KNOWLEDGE_SYNC_RUN_ON_STARTUP", False),  # 启动时是否立即同步
}

# ============================================================
# 知识源配置
# ============================================================
KNOWLEDGE_SOURCE_CONFIG = {
    "root_dir": _resolve_project_path(os.getenv("KNOWLEDGE_SOURCE_ROOT_DIR", "./knowledge_sources")),  # 知识源根目录
    "scan_extensions": set(),  # 扫描的文件扩展名
    "include_seed_data": _get_bool_env("KNOWLEDGE_SYNC_INCLUDE_SEED_DATA", True),  # 是否包含种子数据
}

# ============================================================
# 公共知识分块配置
# ============================================================
PUBLIC_KNOWLEDGE_CHUNK_CONFIG = {
    "chunk_size": max(_get_int_env("PUBLIC_KNOWLEDGE_CHUNK_SIZE", 900), 200),      # 分块大小（字符数）
    "chunk_overlap": max(_get_int_env("PUBLIC_KNOWLEDGE_CHUNK_OVERLAP", 120), 0),  # 分块重叠（字符数）
}

# ============================================================
# 角色 PDF 汇编配置
# ============================================================
ROLE_PDF_COMPENDIUM_CONFIG = {
    "output_dir": _resolve_project_path(os.getenv("ROLE_PDF_COMPENDIUM_DIR", "./generated/domain_pdfs")),  # 输出目录
    "target_entries_per_role": max(_get_int_env("ROLE_PDF_TARGET_ENTRIES_PER_ROLE", 1000), 1),  # 每角色目标条目数
}

# ============================================================
# 文件上传配置
# ============================================================
UPLOAD_CONFIG = {
    "root_dir": _resolve_project_path(os.getenv("UPLOAD_ROOT_DIR", "./uploads")),  # 上传文件根目录
    "max_file_size": _get_int_env("UPLOAD_MAX_FILE_SIZE", 20 * 1024 * 1024),  # 最大文件大小（20MB）
    "pdf_multimodal_max_pages": max(_get_int_env("UPLOAD_PDF_MULTIMODAL_MAX_PAGES", 6), 1),  # 多模态最大页数
    "pdf_multimodal_page_batch_size": max(_get_int_env("UPLOAD_PDF_MULTIMODAL_PAGE_BATCH_SIZE", 2), 1),  # 多模态单批页数
    "pdf_multimodal_parallel_requests": max(_get_int_env("UPLOAD_PDF_MULTIMODAL_PARALLEL_REQUESTS", 2), 1),  # PDF 多模态并发请求数
    "pdf_multimodal_image_dpi": max(_get_int_env("UPLOAD_PDF_MULTIMODAL_IMAGE_DPI", 160), 72),  # 多模态图片 DPI
    "pdf_multimodal_timeout_seconds": max(_get_int_env("UPLOAD_PDF_MULTIMODAL_TIMEOUT_SECONDS", 90), 15),  # 多模态超时
    "image_use_multimodal_fallback": _get_bool_env("UPLOAD_IMAGE_USE_MULTIMODAL_FALLBACK", True),  # 图片 OCR 失败时是否走多模态
    "image_force_multimodal_for_complex": _get_bool_env("UPLOAD_IMAGE_FORCE_MULTIMODAL_FOR_COMPLEX", True),  # 复杂图片是否强制走多模态
    "image_multimodal_min_ocr_chars": max(_get_int_env("UPLOAD_IMAGE_MULTIMODAL_MIN_OCR_CHARS", 24), 1),  # OCR 结果过短阈值
    "allowed_extensions": {  # 允许上传的文件扩展名
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".pdf",
        ".docx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".webp",
    },
    "chunk_size": max(_get_int_env("UPLOAD_CHUNK_SIZE", 900), 200),      # 上传文件分块大小
    "chunk_overlap": max(_get_int_env("UPLOAD_CHUNK_OVERLAP", 120), 0),  # 上传文件分块重叠
}
