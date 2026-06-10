from __future__ import annotations

"""Mock LLM 客户端，用于开发和测试阶段。

不调用真实 LLM API，直接根据检索片段拼接一个简短回答。
"""

from app.schemas.query import QueryUnderstandingResult
from app.services.llm.base import BaseLLMClient, GeneratedAnswer, is_english_language
from app.services.retrievers.base import RetrievedChunk


class MockLLMClient(BaseLLMClient):
    """模拟 LLM 客户端，用于无真实 API 时的本地测试。

    取检索结果中前 3 个片段的摘要拼接为回答。
    """
    def generate_answer(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> GeneratedAnswer:
        english = is_english_language(understanding.detected_language)
        if not retrieved_chunks:
            return GeneratedAnswer(
                answer=(
                    "No relevant context was retrieved for this question. "
                    "Please make sure the PDF has been parsed successfully before trying again."
                    if english else
                    "当前没有检索到可用于回答的问题片段。"
                    "请确认 PDF 已成功解析并建立分块后再试。"
                ),
                metadata={"mode": "fallback_no_context"},
            )

        lead_chunk = retrieved_chunks[0].chunk
        related_snippets = [item.chunk.text[:120] for item in retrieved_chunks[:3]]
        if english:
            answer = (
                f"Based on the content near page {lead_chunk.page_number or '?'} of "
                f"\"{lead_chunk.source_id}\", the passages most relevant to \"{question}\" are: "
                f"{'; '.join(related_snippets)}."
            )
        else:
            answer = (
                f"根据《{lead_chunk.source_id}》第 {lead_chunk.page_number or '?'} 页附近内容，"
                f"与问题“{question}”最相关的片段主要集中在以下信息："
                f"{'；'.join(related_snippets)}。"
            )

        return GeneratedAnswer(
            answer=answer,
            metadata={
                "mode": "mock_llm",
                "used_chunk_count": min(len(retrieved_chunks), 3),
                "note": "Replace MockLLMClient with a production LLM client later.",
            },
        )
