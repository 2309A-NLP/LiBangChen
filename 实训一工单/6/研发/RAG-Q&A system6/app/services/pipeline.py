from __future__ import annotations

import uuid
from time import perf_counter

from app.schemas.query import QueryRequest, QueryResponse
from app.services.llm.base import is_english_language
from app.services.query_understanding import QueryUnderstandingService
from app.services.retrieval_generation import RetrievalGenerationService
from app.services.session_service import SessionService


"""
问答管线服务模块。

串联查询理解、检索生成、会话管理三个阶段，
是用户问题从输入到回答输出的核心编排层。
"""


class QAPipelineService:
    """问答管线：协调查询理解、文档检索与答案生成的完整流程。"""
    def __init__(
        self,
        query_understanding_service: QueryUnderstandingService,
        retrieval_generation_service: RetrievalGenerationService,
        session_service: SessionService,
    ) -> None:
        self.query_understanding_service = query_understanding_service
        self.retrieval_generation_service = retrieval_generation_service
        self.session_service = session_service

    def answer_question(self, payload: QueryRequest) -> QueryResponse:
        """处理用户问题：理解意图 → 检索文档 → 生成回答，同时管理会话上下文。"""
        session_id = self.session_service.ensure_session_id(payload.session_id)
        conversation_messages = self.session_service.build_context_messages(session_id)
        contextualizer = getattr(self.query_understanding_service, "contextualize_question", None)
        if callable(contextualizer):
            contextual_question, rewrite_debug = contextualizer(
                payload.question,
                conversation_messages,
            )
        else:
            contextual_question, rewrite_debug = payload.question, {
                "rewritten": False,
                "reason": "contextualizer_unavailable",
            }

        understanding_started_at = perf_counter()
        understanding = self.query_understanding_service.understand(contextual_question)
        understanding_elapsed_ms = round((perf_counter() - understanding_started_at) * 1000, 2)

        if understanding.clarification_needed:
            answer = understanding.clarification_question or (
                "Please clarify the key reference or time range in your question."
                if is_english_language(understanding.detected_language)
                else "请先补充问题中的关键指代或时间范围。"
            )
            debug = None
            if payload.include_debug:
                debug = {
                    "mode": "clarification_requested",
                    "retrieval_hints": understanding.retrieval_hints,
                    "contextualization": {
                        **rewrite_debug,
                        "question_used_for_understanding": contextual_question,
                    },
                    "timing_ms": {
                        "understanding": understanding_elapsed_ms,
                    },
                }

            response = QueryResponse(
                answer_id=str(uuid.uuid4()),
                session_id=session_id,
                question=payload.question,
                answer=answer,
                citations=[],
                understanding=understanding,
                debug=debug,
            )
            self.session_service.add_user_message(session_id, payload.question)
            self.session_service.add_assistant_message(
                session_id,
                answer,
                metadata={"answer_id": response.answer_id, "strategy": understanding.strategy},
            )
            return response

        response = self.retrieval_generation_service.answer(
            question=payload.question,
            understanding=understanding,
            top_k=payload.top_k,
            include_debug=payload.include_debug,
            timing={"understanding": understanding_elapsed_ms},
            conversation_messages=conversation_messages,
            retrieval_mode=payload.retrieval_mode,
            score_threshold=payload.score_threshold,
            reranker_enabled=payload.reranker_enabled,
            reranker_types=payload.reranker_types,
        )
        response.session_id = session_id
        if payload.include_debug:
            response.debug = {
                **(response.debug or {}),
                "requested_retrieval_mode": payload.retrieval_mode or "default",
                "requested_top_k": payload.top_k,
                "requested_score_threshold": payload.score_threshold,
                "requested_reranker_enabled": payload.reranker_enabled,
                "requested_reranker_types": payload.reranker_types or [],
                "contextualization": {
                    **rewrite_debug,
                    "question_used_for_understanding": contextual_question,
                },
            }

        self.session_service.add_user_message(
            session_id,
            payload.question,
            metadata={"source_files": payload.source_files or []},
        )
        self.session_service.add_assistant_message(
            session_id,
            response.answer,
            metadata={"answer_id": response.answer_id, "strategy": response.understanding.strategy},
        )
        return response
