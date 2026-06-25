"""LLM 客户端工厂模块。

根据配置项 ``LLM_PROVIDER`` 创建对应的 LLM 客户端实例。
支持 ``mock``（测试用）和 ``openai_compatible``（兼容 OpenAI API）两种模式。
"""
from app.core.config import Settings
from app.services.llm.base import BaseLLMClient
from app.services.llm.mock import MockLLMClient
from app.services.llm.openai_compatible import OpenAICompatibleLLMClient


def build_llm_client(settings: Settings) -> BaseLLMClient:
    """根据全局配置构建并返回 LLM 客户端实例。"""
    provider = settings.llm_provider.strip().lower()

    if provider == "mock":
        return MockLLMClient()

    if provider in {"openai_compatible", "openai", "online"}:
        missing_fields: list[str] = []
        if not settings.llm_api_key:
            missing_fields.append("LLM_API_KEY")
        if not settings.llm_base_url:
            missing_fields.append("LLM_BASE_URL")
        if not settings.llm_model:
            missing_fields.append("LLM_MODEL")

        if missing_fields:
            raise ValueError(f"在线回答模型缺少配置项: {', '.join(missing_fields)}")

        return OpenAICompatibleLLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    raise ValueError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")
