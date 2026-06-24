"""
日程提醒智能体 — 全局配置
==========================
统一管理所有配置项，支持环境变量覆盖。
工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务
"""

import os
import logging

# ── 项目路径 ─────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "schedule.db")

# ── LLM API 配置 ─────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    """按优先级读取 API Key: 环境变量 > api_key.txt > 空"""
    key = os.getenv("SILICONFLOW_API_KEY", "")
    if key:
        return key
    key_file = os.path.join(BASE_DIR, "api_key.txt")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return ""

API_KEY = _load_api_key()
BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = os.getenv("SILICONFLOW_MODEL", "Qwen/Qwen3-14B")
TEMPERATURE = float(os.getenv("SILICONFLOW_TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("SILICONFLOW_MAX_TOKENS", "2048"))
TIMEOUT = int(os.getenv("SILICONFLOW_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("SILICONFLOW_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("SILICONFLOW_RETRY_BACKOFF", "1.5"))

# ── Agent 配置 ───────────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "5"))
MAX_HISTORY = int(os.getenv("AGENT_MAX_HISTORY", "20"))
CHECK_INTERVAL = int(os.getenv("AGENT_CHECK_INTERVAL", "30"))  # 提醒检查间隔(秒)

# ── 日志配置 ─────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S",
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
