# -*- coding: utf-8 -*-
"""
安全模块
========
功能：密码哈希、JWT 令牌签发/验证、管理员 API Key 验证、速率限制。

安全特性：
  - PBKDF2-SHA256 密码哈希（120000 次迭代，16 字节随机盐）
  - HMAC-SHA256 JWT 令牌签名
  - 固定窗口速率限制器（线程安全）
"""

import base64       # Base64 编解码
import hashlib      # 哈希算法（SHA256、PBKDF2）
import hmac         # HMAC 签名验证（防时序攻击）
import json         # JSON 序列化
import os           # 操作系统接口（随机数、环境变量）
import threading    # 线程锁（速率限制器线程安全）
import time         # 时间戳


# ============================================================
# 密码哈希配置
# ============================================================
PBKDF2_ALGORITHM = "sha256"       # PBKDF2 哈希算法
PBKDF2_ITERATIONS = 120000        # PBKDF2 迭代次数（越高越安全）
SALT_BYTES = 16                   # 盐值长度（字节）


def hash_password(password: str) -> str:
    """
    使用 PBKDF2-SHA256 哈希密码。
    
    生成随机盐，执行 120000 次迭代哈希。
    返回格式：pbkdf2_sha256$迭代次数$盐(Base64)$哈希(Base64)
    
    Args:
        password: 明文密码
        
    Returns:
        str: 格式化的密码哈希字符串
    """
    salt = os.urandom(SALT_BYTES)  # 生成随机盐
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    # 返回格式：算法$迭代次数$盐$哈希
    return (
        f"pbkdf2_{PBKDF2_ALGORITHM}$"
        f"{PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """
    验证密码与存储的哈希是否匹配。
    
    使用 hmac.compare_digest 进行常量时间比较，防止时序攻击。
    
    Args:
        password: 待验证的明文密码
        stored_hash: 存储的哈希字符串
        
    Returns:
        bool: True 表示密码匹配
    """
    try:
        # 解析存储的哈希格式
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != f"pbkdf2_{PBKDF2_ALGORITHM}":
            return False

        # 解码盐和期望的哈希值
        expected = base64.b64decode(digest_b64.encode("ascii"))
        salt = base64.b64decode(salt_b64.encode("ascii"))
        
        # 使用相同的参数重新计算哈希
        derived = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        # 常量时间比较（防止时序攻击）
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


# ============================================================
# JWT 令牌辅助函数
# ============================================================

def _urlsafe_b64encode(data: bytes) -> str:
    """
    URL 安全的 Base64 编码（去除填充 =）。
    
    Args:
        data: 要编码的字节数据
        
    Returns:
        str: URL 安全的 Base64 字符串
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    """
    URL 安全的 Base64 解码（自动补全填充 =）。
    
    Args:
        value: URL 安全的 Base64 字符串
        
    Returns:
        bytes: 解码后的字节数据
    """
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _get_auth_secret() -> bytes:
    """
    获取 JWT 签名密钥。
    
    优先使用 AUTH_SECRET_KEY 环境变量。
    如果未配置，则使用其他配置项的哈希作为回退密钥。
    
    Returns:
        bytes: 签名密钥
    """
    secret = os.getenv("AUTH_SECRET_KEY", "").strip()
    if secret:
        return secret.encode("utf-8")

    # 回退：使用其他配置项的拼接哈希
    fallback_seed = "|".join(
        part
        for part in (
            os.getenv("OPENAI_API_KEY", "").strip(),
            os.getenv("MYSQL_PASSWORD", "").strip(),
            os.getenv("DATABASE_URL", "").strip(),
            os.getenv("MYSQL_DB", "").strip(),
            "roleplay-system-auth",
        )
        if part
    )
    if not fallback_seed:
        fallback_seed = "roleplay-system-auth-fallback"
    return hashlib.sha256(fallback_seed.encode("utf-8")).digest()


def issue_access_token(user_id: int, username: str, expires_in_seconds: int) -> str:
    """
    签发 JWT 格式的访问令牌。
    
    令牌格式：payload_base64.signature_base64
    载荷包含：sub（用户ID）、username、iat（签发时间）、exp（过期时间）、type
    
    Args:
        user_id: 用户 ID
        username: 用户名
        expires_in_seconds: 过期时间（秒）
        
    Returns:
        str: JWT 令牌字符串
    """
    now = int(time.time())
    payload = {
        "sub": int(user_id),                    # 主题（用户 ID）
        "username": username,                   # 用户名
        "iat": now,                             # 签发时间
        "exp": now + max(int(expires_in_seconds), 1),  # 过期时间
        "type": "access",                       # 令牌类型
    }
    # 序列化载荷并编码
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _urlsafe_b64encode(payload_bytes)
    # HMAC-SHA256 签名
    signature = hmac.new(_get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_urlsafe_b64encode(signature)}"


def verify_access_token(token: str) -> dict | None:
    """
    验证 JWT 令牌的签名和有效期。
    
    Args:
        token: JWT 令牌字符串
        
    Returns:
        dict | None: 验证成功返回载荷字典，失败返回 None
    """
    try:
        # 分离载荷和签名
        payload_b64, signature_b64 = token.split(".", 1)
        
        # 验证签名
        expected = hmac.new(_get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided = _urlsafe_b64decode(signature_b64)
        if not hmac.compare_digest(expected, provided):
            return None

        # 解码载荷
        payload = json.loads(_urlsafe_b64decode(payload_b64).decode("utf-8"))
        
        # 验证令牌类型
        if payload.get("type") != "access":
            return None
        # 验证过期时间
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        # 验证必要字段
        if not payload.get("sub") or not payload.get("username"):
            return None
        return payload
    except Exception:
        return None


def verify_admin_api_key(provided_key: str | None) -> bool:
    """
    验证管理员 API Key。
    
    使用 hmac.compare_digest 进行常量时间比较。
    
    Args:
        provided_key: 提供的 API Key
        
    Returns:
        bool: True 表示验证通过
    """
    expected_key = os.getenv("ADMIN_API_KEY", "").strip()
    if not expected_key or not provided_key:
        return False
    return hmac.compare_digest(provided_key, expected_key)


# ============================================================
# 速率限制器
# ============================================================

class FixedWindowRateLimiter:
    """
    固定窗口速率限制器。
    
    在固定时间窗口内限制请求次数。
    线程安全，使用内存存储。
    
    用法：
        limiter = FixedWindowRateLimiter(limit=10, window_seconds=60)
        allowed, retry_after = limiter.check("user_123")
        if allowed:
            # 处理请求
            pass
        else:
            # 返回 429，retry_after 秒后重试
            pass
    """

    def __init__(self, limit: int, window_seconds: int):
        """
        初始化速率限制器。
        
        Args:
            limit: 时间窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）
        """
        self.limit = max(int(limit), 1)                    # 最大请求数
        self.window_seconds = max(int(window_seconds), 1)  # 时间窗口（秒）
        self._lock = threading.Lock()                      # 线程锁
        self._buckets: dict[str, tuple[int, int]] = {}     # 存储桶 {key: (窗口开始时间, 计数)}

    def check(self, key: str) -> tuple[bool, int]:
        """
        检查是否允许请求。
        
        Args:
            key: 限流键（如用户 ID、IP 地址）
            
        Returns:
            tuple[bool, int]: (是否允许, 重试等待秒数)
        """
        now = int(time.time())
        window_start = now - (now % self.window_seconds)  # 当前窗口开始时间
        
        with self._lock:
            # 获取当前键的存储桶
            current_window, count = self._buckets.get(key, (window_start, 0))
            
            # 如果窗口已过期，重置计数
            if current_window != window_start:
                current_window, count = window_start, 0

            # 检查是否超过限制
            if count >= self.limit:
                retry_after = max(current_window + self.window_seconds - now, 1)
                self._buckets[key] = (current_window, count)
                return False, retry_after  # 拒绝请求

            # 允许请求，增加计数
            self._buckets[key] = (current_window, count + 1)
            return True, 0  # 允许请求
