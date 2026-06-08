from __future__ import annotations

import json
import socket
from urllib import error, request

from app.schemas.query import QueryUnderstandingResult
from app.services.llm.base import BaseLLMClient, GeneratedAnswer, is_english_language
from app.services.retrievers.base import RetrievedChunk


class LLMRemoteError(RuntimeError):
    pass


class OpenAICompatibleLLMClient(BaseLLMClient):
    CHINESE_SYSTEM_PROMPT = """\
你是一个严谨的中文 RAG 问答助手。请基于提供的检索片段回答用户问题，并遵守以下要求：
1. 只能依据给定片段作答，不要补充片段中没有的信息。
2. 如果片段不足以支持结论，明确说明“根据当前检索到的内容，暂时无法确认”。
3. 优先直接回答用户问题，语言简洁、清楚。
4. 不要编造页码、数字、时间或公司事实。
5. 不要输出 markdown 标题，不要解释你的推理过程。
6. 如果涉及收入、金额或表格数据，优先使用与问题范围最一致的表格证据。""".strip()

    ENGLISH_SYSTEM_PROMPT = """\
You are a careful RAG question answering assistant. Answer the user's question only with the retrieved passages and follow these rules:
1. Use only the provided evidence and do not invent missing facts.
2. If the passages are insufficient, clearly say that the answer cannot be confirmed from the retrieved content.
3. Answer directly and clearly in English.
4. Do not fabricate page numbers, figures, dates, or company facts.
5. Do not output markdown headings and do not explain your hidden reasoning.
6. If the question involves revenue, figures, or table data, prefer the table evidence that best matches the user's requested scope.""".strip()

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

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
                    "No relevant passages were retrieved for this question. "
                    "Please make sure the PDF is available in data/source/ or try rephrasing the question."
                    if english else
                    "当前没有检索到可用于回答的问题片段。"
                    "请确认 PDF 已放入 data/source/ 目录，或调整问题后再试。"
                ),
                metadata={"mode": "fallback_no_context"},
            )

        system_prompt = self.ENGLISH_SYSTEM_PROMPT if english else self.CHINESE_SYSTEM_PROMPT
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if conversation_messages:
            messages.extend(conversation_messages)
        messages.append(
            {
                "role": "user",
                "content": self._build_user_prompt(
                    question=question,
                    understanding=understanding,
                    retrieved_chunks=retrieved_chunks,
                ),
            }
        )

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": messages,
        }
        response = self._create_chat_completion(payload)
        answer = self._extract_content(response)

        return GeneratedAnswer(
            answer=answer,
            metadata={
                "mode": "openai_compatible",
                "model": self.model,
                "used_chunk_count": len(retrieved_chunks),
                "history_message_count": len(conversation_messages or []),
                "response_language": "en" if english else "zh",
            },
        )

    def _build_user_prompt(
        self,
        *,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> str:
        english = is_english_language(understanding.detected_language)
        formatted_chunks = []
        for index, item in enumerate(retrieved_chunks, start=1):
            page = item.chunk.page_number if item.chunk.page_number is not None else "unknown"
            if english:
                lines = [
                    f"[Passage {index}]",
                    f"Source: {item.chunk.source_id}",
                    f"Page: {page}",
                    f"Relevance: {item.score}",
                    f"Content: {item.chunk.text}",
                ]
            else:
                lines = [
                    f"[片段{index}]",
                    f"来源: {item.chunk.source_id}",
                    f"页码: {page}",
                    f"相关度: {item.score}",
                    f"内容: {item.chunk.text}",
                ]
            formatted_chunks.append("\n".join(lines))

        sub_questions = understanding.sub_questions or [understanding.normalized_question]
        assumptions = understanding.assumptions or (["None"] if english else ["无"])
        ambiguous_terms = understanding.ambiguous_terms or (["None"] if english else ["无"])

        if english:
            parts = [
                f"User question: {question}",
                f"Normalized question: {understanding.normalized_question}",
                f"Intent: {understanding.intent}",
                f"Answer goal: {understanding.abstracted_goal}",
                f"Sub-questions: {'; '.join(sub_questions)}",
                f"Ambiguous terms: {'; '.join(ambiguous_terms)}",
                f"Assumptions: {'; '.join(assumptions)}",
                "Please answer only based on the following retrieved passages:",
                "\n\n".join(formatted_chunks),
            ]
        else:
            parts = [
                f"用户问题: {question}",
                f"规范化问题: {understanding.normalized_question}",
                f"意图: {understanding.intent}",
                f"抽象目标: {understanding.abstracted_goal}",
                f"子问题: {'；'.join(sub_questions)}",
                f"歧义词: {'；'.join(ambiguous_terms)}",
                f"假设: {'；'.join(assumptions)}",
                "请基于以下检索片段回答：",
                "\n\n".join(formatted_chunks),
            ]
        return "\n\n".join(parts)

    def _create_chat_completion(self, payload: dict[str, object]) -> dict[str, object]:
        endpoint = f"{self.base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = request.Request(endpoint, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRemoteError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LLMRemoteError(f"LLM connection failed: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMRemoteError("LLM request timed out.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMRemoteError("LLM returned invalid JSON.") from exc

        if not isinstance(parsed, dict):
            raise LLMRemoteError("LLM response format is invalid.")
        return parsed

    def _extract_content(self, payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMRemoteError("LLM response is missing choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMRemoteError("LLM response choice is invalid.")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMRemoteError("LLM response is missing message.")

        content = message.get("content")
        if isinstance(content, str):
            normalized = content.strip()
            if normalized:
                return normalized

        if isinstance(content, list):
            text_blocks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            joined = "".join(text_blocks).strip()
            if joined:
                return joined

        raise LLMRemoteError("LLM response does not contain parseable content.")
