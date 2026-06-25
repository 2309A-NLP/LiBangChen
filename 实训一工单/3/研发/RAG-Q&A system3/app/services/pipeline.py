from __future__ import annotations

import re
import uuid
from time import perf_counter

from app.schemas.query import QueryRequest, QueryResponse, QueryUnderstandingResult
from app.services.llm.base import is_english_language
from app.services.query_understanding import QueryUnderstandingService
from app.services.retrieval_generation import RetrievalGenerationService
from app.services.session_service import SessionService


"""
问答管线服务模块。
串联查询理解、文档检索生成、会话管理三个阶段，
是用户问题从输入到回答输出的核心编排层。
"""


class QAPipelineService:
    """问答管线：协调查询理解、文档检索与答案生成的完整流程。"""

    COMPANY_ENTITY_PATTERN = re.compile(
        r"[\u4e00-\u9fffA-Za-z0-9]{2,}(?:股份有限公司|有限责任公司|有限公司|集团|研究院|研究所)"
    )

    ENTITY_NOISE_PREFIXES = (
        "与",
        "和",
        "及",
        "以及",
        "关于",
        "对于",
        "请问",
        "根据",
        "依据",
        "按照",
        "按",
        "就",
    )

    def __init__(
        self,
        query_understanding_service: QueryUnderstandingService,
        retrieval_generation_service: RetrievalGenerationService,
        session_service: SessionService,
        document_ingestion_service=None,
    ) -> None:
        self.query_understanding_service = query_understanding_service
        self.retrieval_generation_service = retrieval_generation_service
        self.session_service = session_service
        self.document_ingestion_service = document_ingestion_service

    def answer_question(self, payload: QueryRequest) -> QueryResponse:
        """处理用户问题：理解意图 -> 检索文档 -> 生成回答，同时管理会话上下文。"""
        session_id = self.session_service.ensure_session_id(payload.session_id)
        conversation_messages = self.session_service.build_context_messages(session_id)

        understanding_started_at = perf_counter()
        understanding = self.query_understanding_service.understand(payload.question)
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

        scope_mismatch = self._detect_document_scope_mismatch(understanding)
        if scope_mismatch is not None:
            answer = self._build_document_scope_mismatch_answer(
                mismatch=scope_mismatch,
                english=is_english_language(understanding.detected_language),
            )
            debug = None
            if payload.include_debug:
                debug = {
                    "mode": "document_scope_mismatch",
                    "queried_entities": scope_mismatch["queried_entities"],
                    "selected_sources": scope_mismatch["selected_sources"],
                    "observed_entities": scope_mismatch["observed_entities"],
                    "retrieval_hints": understanding.retrieval_hints,
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
            self.session_service.add_user_message(
                session_id,
                payload.question,
                metadata={"source_files": payload.source_files or []},
            )
            self.session_service.add_assistant_message(
                session_id,
                answer,
                metadata={"answer_id": response.answer_id, "strategy": "document_scope_mismatch"},
            )
            return response

        response = self.retrieval_generation_service.answer(
            question=payload.question,
            understanding=understanding,
            top_k=payload.top_k,
            include_debug=payload.include_debug,
            timing={"understanding": understanding_elapsed_ms},
            conversation_messages=conversation_messages,
        )
        response.session_id = session_id

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

    def _detect_document_scope_mismatch(
        self,
        understanding: QueryUnderstandingResult,
    ) -> dict[str, list[str]] | None:
        if self.document_ingestion_service is None:
            return None

        raw_entities = understanding.retrieval_hints.get("entities")
        if not isinstance(raw_entities, list):
            return None

        queried_entities = []
        for entity in raw_entities:
            if not isinstance(entity, str):
                continue
            normalized_entity = self._normalize_entity_name(entity)
            if normalized_entity and self.COMPANY_ENTITY_PATTERN.fullmatch(normalized_entity):
                queried_entities.append(normalized_entity)
        if not queried_entities:
            return None

        selected_chunks = self.document_ingestion_service.chunks()
        if not selected_chunks:
            return None

        normalized_texts = [self._normalize_text(chunk.text) for chunk in selected_chunks if chunk.text]
        matched_entities = [
            entity
            for entity in queried_entities
            if any(self._normalize_text(entity) in text for text in normalized_texts)
        ]
        if matched_entities:
            return None

        status = self.document_ingestion_service.status()
        selected_sources = status.get("selected_sources")
        source_files = status.get("source_files")
        if isinstance(selected_sources, list) and selected_sources:
            scope_sources = [item for item in selected_sources if isinstance(item, str) and item.strip()]
        elif isinstance(source_files, list):
            scope_sources = [item for item in source_files if isinstance(item, str) and item.strip()]
        else:
            scope_sources = []

        return {
            "queried_entities": queried_entities,
            "selected_sources": scope_sources,
            "observed_entities": self._extract_observed_entities(selected_chunks),
        }

    def _build_document_scope_mismatch_answer(
        self,
        *,
        mismatch: dict[str, list[str]],
        english: bool,
    ) -> str:
        queried = ", ".join(mismatch["queried_entities"])
        observed = ", ".join(mismatch["observed_entities"])

        if english:
            answer = (
                f"The currently selected document scope does not appear to contain {queried}. "
                "Please upload or switch to the correct prospectus before asking this question again."
            )
            if observed:
                answer += f" The current document content appears to mention {observed} instead."
            return answer

        answer = (
            f"当前选中的文档范围内未检索到“{queried}”这一公司主体。"
            "请先上传或切换到对应公司的招股书后再提问。"
        )
        if observed:
            answer += f" 当前文档内容更可能对应：{observed}。"
        return answer

    def _extract_observed_entities(self, chunks: list) -> list[str]:
        observed: list[str] = []
        for chunk in chunks:
            matches = self.COMPANY_ENTITY_PATTERN.findall(chunk.text or "")
            for entity in matches:
                normalized = self._normalize_entity_name(entity)
                if normalized and normalized not in observed:
                    observed.append(normalized)
                if len(observed) >= 3:
                    return observed
        return observed

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).strip().lower()

    def _normalize_entity_name(self, entity: str) -> str:
        normalized = re.sub(r"\s+", "", entity).strip()
        normalized = normalized.strip("，。！？；：、“”\"'()（）《》[]【】")
        changed = True
        while changed and normalized:
            changed = False
            for prefix in self.ENTITY_NOISE_PREFIXES:
                if normalized.startswith(prefix) and len(normalized) > len(prefix) + 1:
                    normalized = normalized[len(prefix):].strip()
                    changed = True
        return normalized
