# -*- coding: utf-8 -*-
"""
LLM 配置管理模块
================
功能：管理大语言模型（LLM）的配置，包括模型名称、API Key、API 地址、
温度参数、最大 Token 数等。支持从 .env 文件、本地 JSON 配置文件和环境变量
三种来源加载配置，优先级：环境变量 > 本地配置文件 > 默认值。

主要函数：
  - load_llm_config(): 加载 LLM 配置（合并多个来源）
  - save_llm_config(): 保存 LLM 配置到本地 JSON 文件
  - clear_llm_config(): 清除本地配置文件
  - get_llm_status(): 获取 LLM 配置状态（含 API Key 掩码）
  - build_openai_client(): 构建 OpenAI 兼容客户端
  - test_llm_connection(): 测试 LLM 连接
  - diagnose_llm_runtime(): 诊断 LLM 运行时状态
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
LLM_SETTINGS_FILE = BASE_DIR / "llm_settings.local.json"

load_dotenv(BASE_DIR / ".env")

DEFAULT_LLM_CONFIG = {
    "model_name": "gpt-4o-mini",
    "api_key": "",
    "api_base": "https://api.openai.com/v1",
    "temperature": 0.2,
    "top_p": 0.7,
    "repetition_penalty": 1.1,
    "max_new_tokens": 4000,
    "max_tokens": 4000,
    "timeout_seconds": 120.0,
}

DEFAULT_MULTIMODAL_LLM_CONFIG = {
    "model_name": "gpt-4o-mini",
    "api_key": "",
    "api_base": "https://api.openai.com/v1",
    "temperature": 0.05,
    "top_p": 0.7,
    "repetition_penalty": 1.1,
    "max_new_tokens": 8192,
    "max_tokens": 8192,
    "timeout_seconds": 180.0,
}


def _normalize_api_base(api_base: str) -> str:
    """标准化 API 基础地址（去除末尾斜杠）。"""
    value = (api_base or "").strip()
    if not value:
        return DEFAULT_LLM_CONFIG["api_base"]
    return value.rstrip("/")


def _coerce_float(value: Any, default: float) -> float:
    """安全地将值转换为浮点数，失败时返回默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    """安全地将值转换为整数，失败时返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_file_settings() -> Dict[str, Any]:
    """从本地 JSON 配置文件加载 LLM 设置。"""
    if not LLM_SETTINGS_FILE.exists():
        return {}

    try:
        return json.loads(LLM_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_llm_config() -> Dict[str, Any]:
    """
    加载 LLM 配置（合并多个来源）。
    
    优先级：环境变量 > 本地配置文件 > 默认值。
    返回包含 model_name, api_key, api_base, temperature, top_p, repetition_penalty,
    max_new_tokens, max_tokens, timeout_seconds, configured 的字典。
    """
    file_settings = _load_file_settings()

    model_name = os.getenv("LLM_MODEL") or file_settings.get("model_name") or DEFAULT_LLM_CONFIG["model_name"]
    api_key = os.getenv("OPENAI_API_KEY") or file_settings.get("api_key") or DEFAULT_LLM_CONFIG["api_key"]
    api_base = os.getenv("OPENAI_API_BASE") or file_settings.get("api_base") or DEFAULT_LLM_CONFIG["api_base"]
    temperature = os.getenv("LLM_TEMPERATURE", file_settings.get("temperature", DEFAULT_LLM_CONFIG["temperature"]))
    top_p = os.getenv("LLM_TOP_P", file_settings.get("top_p", DEFAULT_LLM_CONFIG["top_p"]))
    repetition_penalty = os.getenv(
        "LLM_REPETITION_PENALTY",
        file_settings.get("repetition_penalty", DEFAULT_LLM_CONFIG["repetition_penalty"]),
    )
    max_new_tokens = os.getenv(
        "LLM_MAX_NEW_TOKENS",
        file_settings.get(
            "max_new_tokens",
            file_settings.get("max_tokens", DEFAULT_LLM_CONFIG["max_new_tokens"]),
        ),
    )
    timeout_seconds = os.getenv(
        "LLM_TIMEOUT_SECONDS",
        file_settings.get("timeout_seconds", DEFAULT_LLM_CONFIG["timeout_seconds"]),
    )

    normalized = {
        "model_name": str(model_name).strip() or DEFAULT_LLM_CONFIG["model_name"],
        "api_key": str(api_key or "").strip(),
        "api_base": _normalize_api_base(str(api_base or "")),
        "temperature": _coerce_float(temperature, DEFAULT_LLM_CONFIG["temperature"]),
        "top_p": _coerce_float(top_p, DEFAULT_LLM_CONFIG["top_p"]),
        "repetition_penalty": _coerce_float(
            repetition_penalty,
            DEFAULT_LLM_CONFIG["repetition_penalty"],
        ),
        "max_new_tokens": _coerce_int(max_new_tokens, DEFAULT_LLM_CONFIG["max_new_tokens"]),
        "timeout_seconds": _coerce_float(timeout_seconds, DEFAULT_LLM_CONFIG["timeout_seconds"]),
    }
    normalized["max_tokens"] = normalized["max_new_tokens"]
    normalized["configured"] = bool(normalized["model_name"] and (normalized["api_key"] or _is_non_openai_base(normalized["api_base"])))
    return normalized


def load_multimodal_llm_config() -> Dict[str, Any]:
    """
    加载文件/PDF/图片解析专用的在线多模态配置。

    这一套配置与普通聊天模型分离，避免上传解析误用本地地址或错误服务。
    """
    model_name = os.getenv("MULTIMODAL_MODEL") or DEFAULT_MULTIMODAL_LLM_CONFIG["model_name"]
    api_key = os.getenv("MULTIMODAL_API_KEY") or ""
    api_base = os.getenv("MULTIMODAL_API_BASE") or DEFAULT_MULTIMODAL_LLM_CONFIG["api_base"]
    temperature = os.getenv(
        "MULTIMODAL_TEMPERATURE",
        DEFAULT_MULTIMODAL_LLM_CONFIG["temperature"],
    )
    top_p = os.getenv(
        "MULTIMODAL_TOP_P",
        DEFAULT_MULTIMODAL_LLM_CONFIG["top_p"],
    )
    repetition_penalty = os.getenv(
        "MULTIMODAL_REPETITION_PENALTY",
        DEFAULT_MULTIMODAL_LLM_CONFIG["repetition_penalty"],
    )
    max_new_tokens = os.getenv(
        "MULTIMODAL_MAX_NEW_TOKENS",
        os.getenv("LLM_MAX_NEW_TOKENS", DEFAULT_MULTIMODAL_LLM_CONFIG["max_new_tokens"]),
    )
    timeout_seconds = os.getenv(
        "MULTIMODAL_TIMEOUT_SECONDS",
        DEFAULT_MULTIMODAL_LLM_CONFIG["timeout_seconds"],
    )

    normalized = {
        "model_name": str(model_name).strip() or DEFAULT_MULTIMODAL_LLM_CONFIG["model_name"],
        "api_key": str(api_key or "").strip(),
        "api_base": _normalize_api_base(str(api_base or "")),
        "temperature": _coerce_float(temperature, DEFAULT_MULTIMODAL_LLM_CONFIG["temperature"]),
        "top_p": _coerce_float(top_p, DEFAULT_MULTIMODAL_LLM_CONFIG["top_p"]),
        "repetition_penalty": _coerce_float(
            repetition_penalty,
            DEFAULT_MULTIMODAL_LLM_CONFIG["repetition_penalty"],
        ),
        "max_new_tokens": _coerce_int(max_new_tokens, DEFAULT_MULTIMODAL_LLM_CONFIG["max_new_tokens"]),
        "timeout_seconds": _coerce_float(timeout_seconds, DEFAULT_MULTIMODAL_LLM_CONFIG["timeout_seconds"]),
    }
    normalized["max_tokens"] = normalized["max_new_tokens"]
    normalized["configured"] = bool(
        normalized["model_name"]
        and normalized["api_key"]
        and not _is_local_api_base(normalized["api_base"])
    )
    return normalized


def save_llm_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    保存 LLM 配置到本地 JSON 文件。
    
    Args:
        payload: 包含要保存的配置字段的字典
        
    Returns:
        Dict[str, Any]: 保存后重新加载的完整配置
    """
    current = load_llm_config()
    merged = {
        "model_name": str(payload.get("model_name", current["model_name"])).strip() or DEFAULT_LLM_CONFIG["model_name"],
        "api_key": str(payload.get("api_key", current["api_key"])).strip(),
        "api_base": _normalize_api_base(str(payload.get("api_base", current["api_base"]) or "")),
        "temperature": _coerce_float(payload.get("temperature", current["temperature"]), current["temperature"]),
        "top_p": _coerce_float(payload.get("top_p", current["top_p"]), current["top_p"]),
        "repetition_penalty": _coerce_float(
            payload.get("repetition_penalty", current["repetition_penalty"]),
            current["repetition_penalty"],
        ),
        "max_new_tokens": _coerce_int(
            payload.get(
                "max_new_tokens",
                payload.get("max_tokens", current["max_new_tokens"]),
            ),
            current["max_new_tokens"],
        ),
        "timeout_seconds": _coerce_float(
            payload.get("timeout_seconds", current["timeout_seconds"]),
            current["timeout_seconds"],
        ),
    }
    merged["max_tokens"] = merged["max_new_tokens"]
    LLM_SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_llm_config()


def clear_llm_config() -> None:
    """清除本地 LLM 配置文件。"""
    if LLM_SETTINGS_FILE.exists():
        LLM_SETTINGS_FILE.unlink()


def get_llm_status() -> Dict[str, Any]:
    """
    获取 LLM 配置状态。
    
    返回包含配置详情和 API Key 掩码后的预览信息。
    """
    config = load_llm_config()
    return {
        "configured": config["configured"],
        "model_name": config["model_name"],
        "api_base": config["api_base"],
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "repetition_penalty": config["repetition_penalty"],
        "max_new_tokens": config["max_new_tokens"],
        "max_tokens": config["max_tokens"],
        "timeout_seconds": config["timeout_seconds"],
        "api_key_preview": mask_api_key(config["api_key"]),
        "settings_file": str(LLM_SETTINGS_FILE),
        "settings_file_exists": LLM_SETTINGS_FILE.exists(),
    }


def build_openai_client(config: Optional[Dict[str, Any]] = None) -> OpenAI:
    """
    构建 OpenAI 兼容客户端。
    
    Args:
        config: LLM 配置字典（可选，默认从 load_llm_config 加载）
        
    Returns:
        OpenAI: 配置好的 OpenAI 客户端实例
        
    Raises:
        ValueError: 未配置可用的 API Key
    """
    resolved = config or load_llm_config()
    api_key = resolved["api_key"] or ("placeholder-api-key" if _is_non_openai_base(resolved["api_base"]) else "")
    if not api_key:
        raise ValueError("未配置可用的 API Key")

    return OpenAI(
        api_key=api_key,
        base_url=resolved["api_base"],
        timeout=float(resolved.get("timeout_seconds", DEFAULT_LLM_CONFIG["timeout_seconds"])),
    )


def build_multimodal_openai_client(config: Optional[Dict[str, Any]] = None) -> OpenAI:
    """
    构建文件解析专用在线多模态客户端。
    """
    resolved = config or load_multimodal_llm_config()
    api_key = str(resolved.get("api_key") or "").strip()
    api_base = str(resolved.get("api_base") or "").strip()

    if not api_key:
        raise ValueError("未配置在线多模态 API Key（MULTIMODAL_API_KEY）")
    if _is_local_api_base(api_base):
        raise ValueError("在线多模态 API 不能指向本地地址，请改为真实在线兼容接口地址")

    return OpenAI(
        api_key=api_key,
        base_url=api_base,
        timeout=float(resolved.get("timeout_seconds", DEFAULT_MULTIMODAL_LLM_CONFIG["timeout_seconds"])),
    )


def test_llm_connection(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    测试 LLM 连接。
    
    先尝试 models.list() 接口，如果失败则回退到 chat.completions 接口。
    
    Args:
        config: LLM 配置字典（可选）
        
    Returns:
        Dict[str, Any]: 包含 ok, message, model_name, api_base 等信息的字典
        
    Raises:
        RuntimeError: 两种接口都失败时抛出
    """
    resolved = config or load_llm_config()
    client = build_openai_client(resolved)

    try:
        models = client.models.list()
        first_model = None
        data = getattr(models, "data", None) or []
        if data:
            first_model = getattr(data[0], "id", None)
        return {
            "ok": True,
            "message": "大模型服务连接成功",
            "model_name": resolved["model_name"],
            "api_base": resolved["api_base"],
            "first_available_model": first_model,
            "method": "models.list",
        }
    except Exception as model_exc:
        # models.list() 失败时回退到 chat.completions 接口
        try:
            response = client.chat.completions.create(
                model=resolved["model_name"],
                messages=[{"role": "user", "content": "Reply with OK only."}],
                temperature=0,
                max_tokens=8,
            )
            content = response.choices[0].message.content if response.choices else None
            return {
                "ok": True,
                "message": "大模型服务连接成功",
                "model_name": resolved["model_name"],
                "api_base": resolved["api_base"],
                "response_preview": content,
                "method": "chat.completions",
            }
        except Exception as chat_exc:
            raise RuntimeError(f"模型列表探测失败: {model_exc}; 聊天接口探测失败: {chat_exc}") from chat_exc


def diagnose_llm_runtime(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    诊断 LLM 运行时状态。
    
    检查配置是否可用、服务是否可达、目标模型是否存在。
    返回详细的诊断结果，包括可用模型列表。
    
    Args:
        config: LLM 配置字典（可选）
        
    Returns:
        Dict[str, Any]: 包含 ok, status, message, models 等信息的诊断结果
    """
    resolved = config or load_llm_config()
    model_name = resolved["model_name"]
    api_base = resolved["api_base"]

    try:
        client = build_openai_client(resolved)
    except Exception as exc:
        return {
            "ok": False,
            "status": "config_error",
            "model_name": model_name,
            "api_base": api_base,
            "message": f"大模型配置不可用: {exc}",
            "models": [],
        }

    try:
        models = client.models.list()
        model_ids = [getattr(item, "id", "") for item in (getattr(models, "data", None) or [])]
    except Exception as exc:
        return {
            "ok": False,
            "status": "service_unreachable",
            "model_name": model_name,
            "api_base": api_base,
            "message": f"大模型服务不可达: {exc}",
            "models": [],
        }

    if model_name in model_ids:
        return {
            "ok": True,
            "status": "ready",
            "model_name": model_name,
            "api_base": api_base,
            "message": f"大模型检查通过，已找到 {model_name}",
            "models": model_ids[:10],
        }

    return {
        "ok": False,
        "status": "model_missing",
        "model_name": model_name,
        "api_base": api_base,
        "message": f"服务可达，但未找到目标模型 {model_name}",
        "models": model_ids[:10],
    }


def mask_api_key(api_key: str) -> str:
    """
    掩码 API Key（仅显示前4位和后4位）。
    
    Args:
        api_key: 原始 API Key
        
    Returns:
        str: 掩码后的 API Key，空字符串返回空
    """
    value = (api_key or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _is_non_openai_base(api_base: str) -> bool:
    """
    判断是否为非 OpenAI 官方 API 地址。
    
    用于区分第三方兼容接口与 OpenAI 官方 API。
    
    Args:
        api_base: API 基础地址
        
    Returns:
        bool: True 表示非 OpenAI 官方地址
    """
    value = (api_base or "").strip().lower()
    return bool(value) and "api.openai.com" not in value


def _is_local_api_base(api_base: str) -> bool:
    """
    判断是否为本地回环或本机绑定地址。
    """
    value = (api_base or "").strip().lower()
    if not value:
        return False
    local_hosts = ("127.0.0.1", "localhost", "0.0.0.0")
    return any(host in value for host in local_hosts)
