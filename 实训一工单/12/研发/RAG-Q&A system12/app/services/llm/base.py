from __future__ import annotations

"""LLM 服务基模块。

定义 LLM 客户端的抽象基类 ``BaseLLMClient`` 以及生成结果数据类
``GeneratedAnswer``。所有具体 LLM 实现需继承 ``BaseLLMClient`` 并
实现 ``generate_answer`` 方法。
"""

from dataclasses import dataclass

from app.schemas.query import QueryUnderstandingResult
from app.services.retrievers.base import RetrievedChunk


@dataclass
class GeneratedAnswer:
    """LLM 生成的回答结果。"""
    answer: str
    metadata: dict[str, object]


class BaseLLMClient:
    """LLM 客户端抽象基类。

    子类需要实现 ``generate_answer`` 方法，根据问题、查询理解结果和
    检索片段生成最终回答。
    """
    def generate_answer(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> GeneratedAnswer:
        raise NotImplementedError


def is_english_language(language: str | None) -> bool:
    return (language or "").strip().lower().startswith("en")
