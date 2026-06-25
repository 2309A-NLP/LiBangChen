from __future__ import annotations

"""兼容 OpenAI Chat Completions 接口的 LLM 客户端实现。

通过标准 HTTP 请求调用任何兼容 OpenAI API 的大语言模型服务，
构造包含检索片段的 prompt 并解析返回的回答内容。
"""

import json
import socket
from urllib import error, request

from app.schemas.query import QueryUnderstandingResult
from app.services.llm.base import BaseLLMClient, GeneratedAnswer
from app.services.retrievers.base import RetrievedChunk


class LLMRemoteError(RuntimeError):
    """LLM 远程调用异常。"""
    pass


class OpenAICompatibleLLMClient(BaseLLMClient):
    """兼容 OpenAI Chat Completions API 的 LLM 客户端。

    通过 urllib 发送 HTTP POST 请求到 ``/chat/completions`` 端点，
    支持配置 API Key、Base URL、模型名称、超时和温度参数。
    """
    SYSTEM_PROMPT = """\
你是一个严谨的中文 RAG 问答助手。请基于提供的检索片段回答用户问题，并遵守以下要求：
1. 只能依据给定片段作答，不要补充片段中没有的信息。
2. 如果片段不足以支持结论，明确说明“根据当前检索到的内容，暂时无法确认”。
3. 优先直接回答用户问题，语言简洁、清楚。
4. 不要编造页码、数字、时间或公司事实。
5. 不要输出 markdown 标题，不要解释你的推理过程。
6. 当问题问及收入、收入数据、收入金额时，仔细查看整个检索片段。如果片段中包含"按客户群体划分的销售情况"或"按行业列示"或"国防领域"或"军用领域"的表格数据和金额，优先使用这些数据，而非"按产品分类"的数据。
7. 注意：检索片段中可能同时包含"按产品分类"和"按客户群体分类"两种表格。回答"军事领域/国防领域/军用领域收入"时，必须使用**按客户群体分类**的"国防领域"表格数据。
""".strip()

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
        if not retrieved_chunks:
            return GeneratedAnswer(
                answer=(
                    "当前没有检索到可用于回答的问题片段。"
                    "请确认 PDF 已放入 data/source/ 目录，"
                    "或调整问题后再试。"
                ),
                metadata={"mode": "fallback_no_context"},
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": self.SYSTEM_PROMPT}]
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
            },
        )

    def _build_user_prompt(
        self,
        *,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> str:
        formatted_chunks = []
        for index, item in enumerate(retrieved_chunks, start=1):
            page = item.chunk.page_number if item.chunk.page_number is not None else "unknown"
            formatted_chunks.append(
                "\n".join(
                    [
                        f"[片段{index}]",
                        f"来源: {item.chunk.source_id}",
                        f"页码: {page}",
                        f"相关度: {item.score}",
                        f"内容: {item.chunk.text}",
                    ]
                )
            )

        sub_questions = understanding.sub_questions or [understanding.normalized_question]
        assumptions = understanding.assumptions or ["无"]
        ambiguous_terms = understanding.ambiguous_terms or ["无"]

        return "\n\n".join(
            [
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
        )

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
            raise LLMRemoteError(f"在线回答模型请求失败，HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LLMRemoteError(f"在线回答模型连接失败: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMRemoteError("在线回答模型请求超时。") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMRemoteError("在线回答模型返回了非法响应。") from exc

        if not isinstance(parsed, dict):
            raise LLMRemoteError("在线回答模型响应格式不正确。")
        return parsed

    def _extract_content(self, payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMRemoteError("在线回答模型响应中缺少 choices。")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMRemoteError("在线回答模型响应结构异常。")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMRemoteError("在线回答模型响应中缺少 message。")

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

        raise LLMRemoteError("在线回答模型响应中缺少可解析的 content。")
