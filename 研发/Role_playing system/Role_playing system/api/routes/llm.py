# -*- coding: utf-8 -*-
"""
LLM 管理路由模块
功能：提供 LLM（大语言模型）配置管理的 API 接口。
包括查看状态、更新配置、清除配置、连接测试、运行时诊断等。

接口列表：
  - GET /api/llm/status: 获取 LLM 配置状态（不暴露 API Key）
  - POST /api/llm/config: 更新 LLM 配置
  - DELETE /api/llm/config: 清除 LLM 配置
  - POST /api/llm/test: 测试 LLM 连接
  - GET /api/llm/runtime-check: 运行时诊断

依赖：
  - require_admin: 管理员权限验证
  - llm_settings: LLM 配置管理模块
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from llm_settings import clear_llm_config, diagnose_llm_runtime, get_llm_status, load_llm_config, save_llm_config, test_llm_connection

from ..dependencies import raise_http_error, require_admin
from ..schemas import LLMConfigPayload

router = APIRouter()


@router.get("/api/llm/status")
async def get_llm_runtime_status(_: None = Depends(require_admin)):
    """
    获取 LLM 配置状态（管理员）。
    
    返回当前 LLM 配置信息，不暴露 API Key。
    
    Returns:
        dict: LLM 配置状态
    """
    return {"code": 200, "data": get_llm_status()}


@router.post("/api/llm/config")
async def update_llm_config(payload: LLMConfigPayload, _: None = Depends(require_admin)):
    """
    更新 LLM 配置（管理员）。
    
    保存 LLM 模型名称、API Key、API Base、温度等参数。
    
    Args:
        payload: LLM 配置参数
        
    Returns:
        dict: 更新后的配置信息（不包含 API Key）
    """
    try:
        config = save_llm_config(payload.model_dump())
        return {
            "code": 200,
            "message": "模型配置已保存",
            "data": {
                "configured": config["configured"],
                "model_name": config["model_name"],
                "api_base": config["api_base"],
                "temperature": config["temperature"],
                "max_tokens": config["max_tokens"],
                "timeout_seconds": config["timeout_seconds"],
            },
        }
    except Exception as exc:
        raise_http_error("Update LLM config", exc)


@router.delete("/api/llm/config")
async def delete_llm_config(_: None = Depends(require_admin)):
    """
    清除 LLM 配置（管理员）。
    
    删除已保存的 LLM 配置信息。
    
    Returns:
        dict: 清除结果
    """
    clear_llm_config()
    return {"code": 200, "message": "模型配置已清除"}


@router.post("/api/llm/test")
async def test_llm_runtime(_: None = Depends(require_admin)):
    """
    测试 LLM 连接（管理员）。
    
    使用当前配置进行一次实时 LLM 连接测试。
    
    Returns:
        dict: 测试结果（成功/失败及详细信息）
    """
    try:
        result = test_llm_connection(load_llm_config())
        return {"code": 200, "message": result["message"], "data": result}
    except Exception as exc:
        raise_http_error("Test LLM runtime", exc)


@router.get("/api/llm/runtime-check")
async def get_llm_runtime_check(_: None = Depends(require_admin)):
    """
    运行时诊断（管理员）。
    
    返回当前 LLM 配置的详细运行时诊断信息。
    
    Returns:
        dict: 运行时诊断结果
    """
    return {"code": 200, "data": diagnose_llm_runtime(load_llm_config())}
