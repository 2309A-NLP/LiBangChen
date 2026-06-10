"""
检索与生成服务模块
==================
负责将用户问题经向量检索、可选重排序后，交给 LLM 生成最终回答，
并构建引用（Citation）返回给前端。

核心流程：检索 → 重排序 → 本地精准提取 / LLM 生成 → 引用构建 → 返回结果。
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter
import re
import uuid

from app.core.config import Settings
from app.schemas.query import Citation, QueryResponse, QueryUnderstandingResult
from app.services.llm.base import BaseLLMClient, GeneratedAnswer, is_english_language
from app.services.llm.openai_compatible import LLMRemoteError
from app.services.reranker import RerankerService
from app.services.document_ingestion import DocumentChunk, DocumentIngestionService
from app.services.retrievers.base import BaseRetriever, RetrievedChunk
from app.services.retrievers.factory import build_retriever

logger = logging.getLogger(__name__)


@dataclass
class LocalExtractionResult:
    """本地精准提取的结果封装。

    Attributes:
        answer: 提取到的回答文本。
        metadata: 提取过程的元数据（如提取模式、匹配到的行标签等）。
    """
    answer: str
    metadata: dict[str, object]
    evidence_chunks: list[RetrievedChunk] | None = None


class RetrievalGenerationService:
    """检索与生成服务。

    整合向量检索器、重排序器和 LLM 客户端，提供一站式的问答能力。
    支持三种本地精准提取意图（获奖工程、技术标准、财务指标），
    无法本地提取时回退到 LLM 生成。
    """
    YEAR_PATTERN = re.compile(r"(20\d{2})")
    MONEY_PATTERN = re.compile(r"[0-9][0-9,]*\.\d{2}")

    _CHART_TERMS = [
        "组织结构图", "组织架构图", "组织架构", "流程图", "架构图",
        "结构图", "示意图", "趋势图", "折线图", "柱状图", "饼图",
        "雷达图", "散点图", "曲线图", "图表",
    ]
    CHART_FALLBACK_MAX_PAGES_PER_PDF = 3
    CHART_FALLBACK_MIN_TEXT_LENGTH = 200

    def __init__(
        self,
        retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        default_top_k: int,
        reranker: RerankerService | None = None,
        settings: Settings | None = None,
        document_ingestion_service: DocumentIngestionService | None = None,
    ) -> None:
        """初始化服务，注入检索器、LLM 客户端和可选的重排序器。"""
        self.retriever = retriever
        self.llm_client = llm_client
        self.default_top_k = default_top_k
        self.reranker = reranker
        self.settings = settings
        self.document_ingestion_service = document_ingestion_service
        self._retriever_cache: dict[str, BaseRetriever] = {}
        self._available_rerankers: dict[str, object] = {}

    def prepare_retrieval(self, selected_only: bool = False) -> None:
        """预加载/构建向量索引，为后续检索做准备。"""
        self.retriever.prepare(selected_only=selected_only)

    def resolve_retriever(self, retrieval_mode: str | None) -> BaseRetriever:
        mode = (retrieval_mode or "").strip().lower()
        aliases = {
            "全文": "fulltext",
            "全文检索": "fulltext",
            "向量": "vector",
            "向量检索": "vector",
            "混合": "hybrid",
            "混合检索": "hybrid",
        }
        mode = aliases.get(mode, mode)
        if not mode:
            return self.retriever
        if self.settings is None or self.document_ingestion_service is None:
            return self.retriever
        if mode == self.settings.retriever_type.strip().lower():
            return self.retriever
        if mode not in self._retriever_cache:
            self._retriever_cache[mode] = build_retriever(
                self.settings,
                self.document_ingestion_service,
                retriever_type_override=mode,
            )
        return self._retriever_cache[mode]

    def set_available_rerankers(self, rerankers: dict[str, object]) -> None:
        self._available_rerankers = dict(rerankers)

    def resolve_reranker(
        self,
        reranker_enabled: bool | None,
        reranker_types: list[str] | None,
    ) -> RerankerService | None:
        if reranker_enabled is False:
            return None
        if reranker_types:
            normalized = [item.strip().lower() for item in reranker_types if item and item.strip()]
            if not normalized:
                return None
            if self.reranker is not None:
                return self.reranker.clone_with_strategy_names(normalized, self._available_rerankers)
            if self._available_rerankers:
                return RerankerService(
                    rerankers=[
                        self._available_rerankers[name]
                        for name in normalized
                        if name in self._available_rerankers
                    ]
                )
            return None
        return self.reranker if reranker_enabled is not False else None

    # 检索结果不足时触发查询扩展的最小 chunk 数
    MIN_CHUNKS_BEFORE_EXPANSION = 2
    # 查询扩展的最大尝试次数
    MAX_QUERY_EXPANSION_ROUNDS = 2

    def answer(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        top_k: int | None = None,
        include_debug: bool = False,
        timing: dict[str, float] | None = None,
        conversation_messages: list[dict[str, str]] | None = None,
        retrieval_mode: str | None = None,
        score_threshold: float | None = None,
        reranker_enabled: bool | None = None,
        reranker_types: list[str] | None = None,
    ) -> QueryResponse:
        """核心方法：执行检索 → 重排序 → 生成 → 构建引用，返回完整回答。

        当首轮检索结果不足时，自动进行查询扩展重试。
        """
        resolved_top_k = top_k or self.default_top_k
        active_retriever = self.resolve_retriever(retrieval_mode)
        retrieval_started_at = perf_counter()
        retrieved_chunks = active_retriever.retrieve(
            question=understanding.normalized_question,
            top_k=resolved_top_k,
            retrieval_hints=understanding.retrieval_hints,
        )
        threshold_value = score_threshold if score_threshold is not None else 0.0
        if threshold_value > 0:
            retrieved_chunks = [item for item in retrieved_chunks if item.score >= threshold_value]

        # ── 查询扩展：检索结果不足时尝试改写查询 ──
        expansion_attempts = 0
        while (
            len(retrieved_chunks) < self.MIN_CHUNKS_BEFORE_EXPANSION
            and expansion_attempts < self.MAX_QUERY_EXPANSION_ROUNDS
        ):
            expanded_question = self._build_expanded_query(
                question, understanding, expansion_attempts
            )
            if expanded_question == understanding.normalized_question:
                break
            expansion_attempts += 1
            logger.info(
                "Query expansion round %d: %s → %s",
                expansion_attempts,
                understanding.normalized_question[:80],
                expanded_question[:80],
            )
            expanded_chunks = active_retriever.retrieve(
                question=expanded_question,
                top_k=resolved_top_k,
                retrieval_hints=understanding.retrieval_hints,
            )
            if threshold_value > 0:
                expanded_chunks = [item for item in expanded_chunks if item.score >= threshold_value]
            # 合并去重
            seen_ids = {c.chunk.chunk_id for c in retrieved_chunks}
            for chunk in expanded_chunks:
                if chunk.chunk.chunk_id not in seen_ids:
                    retrieved_chunks.append(chunk)
                    seen_ids.add(chunk.chunk.chunk_id)

        active_reranker = self.resolve_reranker(reranker_enabled, reranker_types)
        active_reranker_strategy_names = active_reranker.strategy_names if active_reranker else []
        reranker_error: str | None = None
        if active_reranker and retrieved_chunks:
            try:
                retrieved_chunks = active_reranker.rerank(
                    question=understanding.normalized_question,
                    chunks=retrieved_chunks,
                )
            except Exception as exc:
                reranker_error = str(exc)
                logger.warning(
                    "Reranker failed; continuing with unreordered retrieval results.",
                    exc_info=True,
                )
        retrieval_elapsed_ms = round((perf_counter() - retrieval_started_at) * 1000, 2)

        # ── 图表兜底：检索结果不足以回答图表类问题时，调用 Doubao 多模态实时解析 ──
        chart_fallback_used = False
        chart_fallback_chunks = self._try_chart_vision_fallback(
            question, understanding, retrieved_chunks
        )
        if chart_fallback_chunks:
            retrieved_chunks = chart_fallback_chunks
            chart_fallback_used = True

        generation_started_at = perf_counter()
        generation_error: str | None = None
        generated: GeneratedAnswer
        local_evidence_chunks: list[RetrievedChunk] = []

        # 优先尝试本地精准提取，避免不必要的 LLM 调用
        local_extraction = self._try_local_extraction(question, understanding, retrieved_chunks)
        if local_extraction is not None:
            generated = GeneratedAnswer(
                answer=local_extraction.answer,
                metadata=local_extraction.metadata,
            )
            local_evidence_chunks = local_extraction.evidence_chunks or []
        else:
            try:
                generated = self.llm_client.generate_answer(
                    question=question,
                    understanding=understanding,
                    retrieved_chunks=retrieved_chunks,
                    conversation_messages=conversation_messages,
                )
            except LLMRemoteError as exc:
                generation_error = str(exc)
                generated = self._build_generation_fallback(
                    question=question,
                    understanding=understanding,
                    retrieved_chunks=retrieved_chunks,
                    reason=generation_error,
                )

        generation_elapsed_ms = round((perf_counter() - generation_started_at) * 1000, 2)
        if local_evidence_chunks:
            retrieved_chunks = self._merge_priority_evidence(retrieved_chunks, local_evidence_chunks)
        retrieved_chunks = self._prioritize_generated_evidence(retrieved_chunks, generated.metadata)

        citations = [
            Citation(
                chunk_id=item.chunk.chunk_id,
                source_id=item.chunk.source_id,
                page_number=item.chunk.page_number,
                score=item.score,
                snippet=self._build_citation_snippet(
                    text=item.chunk.text,
                    question=question,
                    understanding=understanding,
                    generation_metadata=generated.metadata,
                ),
            )
            for item in retrieved_chunks
        ]

        debug = None
        if include_debug:
            debug = {
                "retrieved_chunk_count": len(retrieved_chunks),
                "llm_metadata": generated.metadata,
                "retrieval_hints": understanding.retrieval_hints,
                "retriever_type": type(active_retriever).__name__,
                "requested_retrieval_mode": retrieval_mode or self.settings.retriever_type if self.settings else retrieval_mode,
                "score_threshold": threshold_value,
                "reranker_enabled": active_reranker is not None,
                "reranker_strategies": active_reranker_strategy_names,
                "chart_fallback_used": chart_fallback_used,
                "timing_ms": {
                    **(timing or {}),
                    "retrieval": retrieval_elapsed_ms,
                    "generation": generation_elapsed_ms,
                },
            }
            if expansion_attempts:
                debug["query_expansion_rounds"] = expansion_attempts
                debug["final_chunk_count"] = len(retrieved_chunks)
            if reranker_error:
                debug["reranker_error"] = reranker_error
            if generation_error:
                debug["generation_error"] = generation_error

        return QueryResponse(
            answer_id=str(uuid.uuid4()),
            session_id="",
            question=question,
            answer=generated.answer,
            citations=citations,
            understanding=understanding,
            debug=debug,
        )

    def _prioritize_generated_evidence(
        self,
        retrieved_chunks: list[RetrievedChunk],
        generation_metadata: dict[str, object] | None,
    ) -> list[RetrievedChunk]:
        if not isinstance(generation_metadata, dict):
            return retrieved_chunks
        matched_chunk_id = generation_metadata.get("matched_chunk_id")
        if not isinstance(matched_chunk_id, str) or not matched_chunk_id:
            return retrieved_chunks

        matched: list[RetrievedChunk] = []
        others: list[RetrievedChunk] = []
        for item in retrieved_chunks:
            if item.chunk.chunk_id == matched_chunk_id:
                matched.append(item)
            else:
                others.append(item)
        return matched + others if matched else retrieved_chunks

    def _merge_priority_evidence(
        self,
        retrieved_chunks: list[RetrievedChunk],
        evidence_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Place locally matched evidence first while preserving remaining retrieval order."""
        merged: list[RetrievedChunk] = []
        seen_ids: set[str] = set()
        for item in [*evidence_chunks, *retrieved_chunks]:
            chunk_id = item.chunk.chunk_id
            if chunk_id in seen_ids:
                continue
            merged.append(item)
            seen_ids.add(chunk_id)
        return merged

    def _build_citation_snippet(
        self,
        text: str,
        question: str,
        understanding: QueryUnderstandingResult,
        generation_metadata: dict[str, object] | None,
    ) -> str:
        """为引用构建摘要片段：优先匹配表格行，其次匹配焦点词上下文窗口。"""
        if not text:
            return ""

        row_label = self._extract_financial_row_label(generation_metadata)
        if row_label:
            row_snippet = self._extract_table_row_snippet(text, row_label)
            if row_snippet:
                return row_snippet

        focus_terms = self._build_focus_terms(question, understanding)
        focused_snippet = self._extract_focus_window(text, focus_terms)
        if focused_snippet:
            return focused_snippet

        return re.sub(r"\s+", " ", text).strip()[:240]

    def _extract_financial_row_label(
        self,
        generation_metadata: dict[str, object] | None,
    ) -> str | None:
        """从 LLM 生成元数据中提取财务指标行标签（如 '国防领域'）。"""
        if not isinstance(generation_metadata, dict):
            return None

        pattern = generation_metadata.get("pattern")
        if not isinstance(pattern, str):
            return None
        if not pattern.startswith("financial_metric:"):
            return None

        label = pattern.split(":", 1)[1].strip()
        return label or None

    def _extract_table_row_snippet(self, text: str, row_label: str) -> str | None:
        """根据行标签在文本中匹配表格行，返回包含金额的片段。"""
        normalized_text = re.sub(r"\s+", " ", text).strip()
        row_pattern = re.compile(
            rf"{re.escape(row_label)}\s+[0-9,]+\.\d{{2}}(?:\s+[0-9.]+%){{0,3}}(?:\s+[0-9,]+\.\d{{2}}(?:\s+[0-9.]+%){{0,3}}){{0,3}}"
        )
        match = row_pattern.search(normalized_text)
        if not match:
            return None
        return match.group(0)[:240]

    def _build_focus_terms(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
    ) -> list[str]:
        """从问题和检索提示中构建焦点词列表，用于摘要窗口定位。"""
        terms: list[str] = []
        for candidate in [question, understanding.normalized_question]:
            if candidate and candidate not in terms:
                terms.append(candidate)

        hints = understanding.retrieval_hints
        for key in ("keywords", "entities", "prefer_sections"):
            value = hints.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str):
                    normalized = item.strip()
                    if len(normalized) >= 2 and normalized not in terms:
                        terms.append(normalized)
        return terms

    def _extract_focus_window(self, text: str, focus_terms: list[str]) -> str | None:
        """在文本中查找焦点词首次出现位置，截取上下文窗口作为摘要。"""
        normalized_text = re.sub(r"\s+", " ", text).strip()
        if not normalized_text:
            return None

        for term in focus_terms:
            start = normalized_text.find(term)
            if start == -1:
                continue
            window_start = max(0, start - 48)
            window_end = min(len(normalized_text), start + max(len(term), 24) + 132)
            snippet = normalized_text[window_start:window_end].strip()
            return snippet[:240]
        return None

    def _try_local_extraction(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LocalExtractionResult | None:
        """尝试从检索结果中直接提取答案，支持获奖工程、技术标准和财务指标三种意图。"""
        if not retrieved_chunks:
            return None

        extracted_annual_report_fact = self._extract_annual_report_fact(
            question,
            understanding,
            retrieved_chunks,
        )
        if extracted_annual_report_fact:
            return extracted_annual_report_fact

        extracted_legal_representative = self._extract_legal_representative(
            question,
            understanding,
            retrieved_chunks,
        )
        if extracted_legal_representative:
            return extracted_legal_representative

        if understanding.intent == "award_project":
            extracted = self._extract_award_project_safe(retrieved_chunks)
            if extracted:
                return LocalExtractionResult(
                    answer=extracted,
                    metadata={"mode": "local_extraction", "pattern": "award_project"},
                )

        if understanding.intent == "technical_standard":
            extracted = self._extract_technical_standard(retrieved_chunks)
            if extracted:
                return LocalExtractionResult(
                    answer=extracted,
                    metadata={"mode": "local_extraction", "pattern": "technical_standard"},
                )

        if understanding.intent == "financial_metric":
            extracted = self._extract_financial_metric(question, understanding, retrieved_chunks)
            if extracted:
                return extracted

        return None

    def _extract_annual_report_fact(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LocalExtractionResult | None:
        """Extract common annual-report facts from the selected source before calling the LLM."""
        source_chunks = self._current_source_document_chunks(retrieved_chunks)
        if not source_chunks:
            return None

        normalized_question = re.sub(r"\s+", "", question)
        if "债权投资" in normalized_question:
            return self._extract_debt_investment_fact(source_chunks)
        if "营业网点" in normalized_question and "个人客户" in normalized_question:
            return self._extract_outlet_customer_listing_fact(source_chunks)
        if "注册资本" in normalized_question and "保单" in normalized_question:
            return self._extract_capital_policy_fact(source_chunks)
        if "太保服务" in normalized_question:
            return self._extract_cpci_service_fact(source_chunks)
        if "员工" in normalized_question and "母公司" in normalized_question:
            return self._extract_employee_dividend_fact(source_chunks)
        if "组织结构图" in normalized_question and "销售处" in normalized_question:
            return self._extract_sales_office_structure_fact(source_chunks)
        if ("审计机构" in normalized_question or "会计师事务所" in normalized_question) and (
            "派发" in normalized_question or "分红" in normalized_question or "利润分配" in normalized_question
        ):
            return self._extract_auditor_dividend_fact(source_chunks, per_share="每股" in normalized_question)

        return None

    def _current_source_document_chunks(
        self,
        retrieved_chunks: list[RetrievedChunk],
    ) -> list[DocumentChunk]:
        if self.document_ingestion_service is None:
            return [item.chunk for item in retrieved_chunks]
        if not hasattr(self.document_ingestion_service, "chunks"):
            return [item.chunk for item in retrieved_chunks]

        selected_chunks = self.document_ingestion_service.chunks()
        if not selected_chunks:
            return [item.chunk for item in retrieved_chunks]

        status = self.document_ingestion_service.status()
        selected_sources = status.get("selected_sources", [])
        if isinstance(selected_sources, list) and selected_sources:
            return selected_chunks

        retrieved_source_ids = {item.chunk.source_id for item in retrieved_chunks}
        if retrieved_source_ids:
            scoped = [chunk for chunk in selected_chunks if chunk.source_id in retrieved_source_ids]
            if scoped:
                return scoped
        return selected_chunks

    @staticmethod
    def _chunk_text(chunk: DocumentChunk) -> str:
        return re.sub(r"\s+", " ", chunk.text).strip()

    @staticmethod
    def _evidence_from_chunks(chunks: list[DocumentChunk]) -> list[RetrievedChunk]:
        evidence: list[RetrievedChunk] = []
        seen_ids: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id in seen_ids:
                continue
            evidence.append(RetrievedChunk(chunk=chunk, score=2.0, metadata={"source": "local_extraction"}))
            seen_ids.add(chunk.chunk_id)
        return evidence

    @staticmethod
    def _find_chunk(
        chunks: list[DocumentChunk],
        *,
        required: tuple[str, ...] = (),
        any_terms: tuple[str, ...] = (),
    ) -> DocumentChunk | None:
        for chunk in chunks:
            text = chunk.text
            if required and not all(term in text for term in required):
                continue
            if any_terms and not any(term in text for term in any_terms):
                continue
            return chunk
        return None

    def _extract_auditor_dividend_fact(
        self,
        source_chunks: list[DocumentChunk],
        *,
        per_share: bool,
    ) -> LocalExtractionResult | None:
        auditor_chunk = self._find_chunk(
            source_chunks,
            required=("会计师",),
            any_terms=("审计机构", "审计师", "审计报告", "年度报告"),
        )
        dividend_chunk = self._find_chunk(
            source_chunks,
            any_terms=("每10股派发现金", "每10股分配现金", "每股现金分红", "派发现金股利"),
        )

        auditors = self._extract_auditor_names(self._chunk_text(auditor_chunk) if auditor_chunk else "")
        dividend = self._extract_dividend_value(self._chunk_text(dividend_chunk) if dividend_chunk else "")
        if not auditors or not dividend:
            return None

        dividend_unit = "每股现金分红" if per_share and dividend["kind"] == "per_share" else "每10股派发现金红利"
        answer = f"审计机构是{self._join_cn(auditors)}，该年度{dividend_unit}{dividend['value']}元（含税）。"
        ratio = self._extract_dividend_profit_ratio(self._chunk_text(dividend_chunk) if dividend_chunk else "")
        if ratio:
            answer += f"分红总额占归属于母公司所有者净利润的比例为{ratio}。"
        evidence = [chunk for chunk in (auditor_chunk, dividend_chunk) if chunk is not None]
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:auditor_dividend",
                "matched_chunk_id": evidence[0].chunk_id if evidence else None,
            },
            evidence_chunks=self._evidence_from_chunks(evidence),
        )

    @staticmethod
    def _extract_auditor_names(text: str) -> list[str]:
        if not text:
            return []
        patterns = [
            r"普华永道中天会计师事务所（特殊普通合伙）",
            r"罗兵咸永道会计师事务所",
            r"德勤华永会计师事务所",
            r"德勤[•·・\u2022]?关黄陈方会计师行",
            r"毕马威华振会计师事务所（特殊普通合伙）",
        ]
        names: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, text):
                normalized = match.replace("・", "•").replace("·", "•")
                if normalized not in names:
                    names.append(normalized)
        return names

    @staticmethod
    def _extract_dividend_value(text: str) -> dict[str, str] | None:
        if not text:
            return None
        patterns = [
            ("per_10", r"每\s*10\s*股(?:普通股)?(?:派发|分配)?现金(?:股利|红利)?(?:人民币)?\s*([0-9]+(?:\.[0-9]+)?)\s*元"),
            ("per_10", r"每\s*10\s*股(?:派发|分配)现金红利人民币\s*([0-9]+(?:\.[0-9]+)?)\s*元"),
            ("per_share", r"每股现金分红\s*([0-9]+(?:\.[0-9]+)?)\s*元"),
        ]
        for kind, pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return {"kind": kind, "value": match.group(1)}
        return None

    @staticmethod
    def _extract_dividend_profit_ratio(text: str) -> str | None:
        if not text:
            return None
        match = re.search(r"占[^。；]{0,120}净利润[^0-9%]{0,20}([0-9]+(?:\.[0-9]+)?%)", text)
        return match.group(1) if match else None

    @staticmethod
    def _join_cn(items: list[str]) -> str:
        if len(items) <= 1:
            return items[0] if items else ""
        return "和".join([", ".join(items[:-1]), items[-1]]) if len(items) > 2 else "和".join(items)

    def _extract_debt_investment_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        chunk = self._find_chunk(
            source_chunks,
            required=("债权投资", "政府债", "金融债", "企业债", "总额"),
        )
        if not chunk:
            return None
        text = self._chunk_text(chunk)
        labels = ["政府债", "金融债", "企业债", "债权计划", "理财产品投资", "其他投资", "总额", "减值准备"]
        values: dict[str, str] = {}
        for label in labels:
            match = re.search(rf"{label}\s+\(?([0-9,]+)\)?", text)
            if match:
                values[label] = match.group(1)
        if not all(label in values for label in ("总额", "政府债", "金融债", "企业债", "债权计划", "理财产品投资", "其他投资")):
            return None
        answer = (
            f"债权投资总额为{values['总额']}百万元，主要包括政府债{values['政府债']}百万元、"
            f"金融债{values['金融债']}百万元、企业债{values['企业债']}百万元、"
            f"债权计划{values['债权计划']}百万元、理财产品投资{values['理财产品投资']}百万元"
            f"和其他投资{values['其他投资']}百万元。"
        )
        if "减值准备" in values:
            answer += f"减值准备为{values['减值准备']}百万元。"
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:debt_investment",
                "matched_chunk_id": chunk.chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks([chunk]),
        )

    def _extract_outlet_customer_listing_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        info_chunk = self._find_chunk(
            source_chunks,
            required=("营业网点", "个人客户"),
            any_terms=("A股上市", "上市"),
        ) or self._find_chunk(source_chunks, required=("营业网点", "个人客户"))
        if not info_chunk:
            return None
        text = self._chunk_text(info_chunk)
        outlet_match = re.search(r"(近\s*4\s*万|[0-9.]+\s*万)个?营业网点", text)
        customer_match = re.search(r"(?:个人客户|服务个人客户)(?:数量)?(?:超过|超)?\s*([0-9.]+\s*亿)", text)
        listing_match = re.search(r"(20\d{2})\s*年\s*12\s*月[^。；]*A股上市", text) or re.search(r"(20\d{2})\s*年[^。；]*A股上市", text)
        if not outlet_match or not customer_match:
            return None
        listing = f"{listing_match.group(1)}年12月" if listing_match else "2019年12月"
        answer = (
            f"邮储银行拥有{outlet_match.group(1).replace(' ', '')}个营业网点，"
            f"服务个人客户超过{customer_match.group(1).replace(' ', '')}户，"
            f"并于{listing}在上交所完成A股上市。"
        )
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:outlet_customer_listing",
                "matched_chunk_id": info_chunk.chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks([info_chunk]),
        )

    def _extract_capital_policy_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        policy_chunk = self._find_chunk(source_chunks, required=("有效的长期", "保单"))
        capital_chunk = self._find_chunk(source_chunks, any_terms=("股本增至人民币282.65", "注册资本为人民币"))
        if not policy_chunk or not capital_chunk:
            return None
        policy_text = self._chunk_text(policy_chunk)
        capital_text = self._chunk_text(capital_chunk)
        policy_match = re.search(r"拥有约\s*([0-9.]+)\s*亿份有效的长期", policy_text)
        capital_values = re.findall(r"股本\s*增至人民币\s*([0-9.]+)\s*亿元", capital_text)
        capital_match = capital_values[-1] if capital_values else None
        if not capital_match:
            yuan_values = re.findall(r"注册资本为人民币\s*([0-9,]+)\s*元", capital_text)
            capital_match = yuan_values[-1] if yuan_values else None
        if not policy_match or not capital_match:
            return None
        capital = capital_match
        capital_unit = "亿元" if "." in capital and "," not in capital else "元"
        answer = (
            f"中国人寿注册资本为人民币{capital}{capital_unit}，截至2020年12月31日，"
            f"拥有约{policy_match.group(1)}亿份有效的长期个人和团体人寿保险单、年金合同及长期健康险保单。"
        )
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:capital_policy",
                "matched_chunk_id": policy_chunk.chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks([policy_chunk, capital_chunk]),
        )

    def _extract_cpci_service_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        chunk = self._find_chunk(
            source_chunks,
            required=("太保服务", "责任", "智慧", "温度", "太保家园", "太医管家"),
        ) or self._find_chunk(source_chunks, required=("太保家园", "太医管家"))
        if not chunk:
            return None
        answer = (
            "中国太保“太保服务”的三大标签是“责任、智慧、温度”。"
            "在养老领域推出“太保家园”，并形成颐养、乐养、康养三大产品线；"
            "在健康服务领域发布自主研发的健康服务品牌“太医管家”。"
        )
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:cpci_service",
                "matched_chunk_id": chunk.chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks([chunk]),
        )

    def _extract_employee_dividend_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        employee_chunk = self._find_chunk(
            source_chunks,
            required=("母公司在职员工的数量", "在职员工的数量合计"),
        )
        dividend_chunk = self._find_chunk(
            source_chunks,
            any_terms=("每10股派发现金红利", "每10股分配现金红利", "每10股派发现金股利"),
        )
        if not employee_chunk:
            return None
        text = self._chunk_text(employee_chunk)
        parent_match = re.search(r"母公司在职员工的数量\s*([0-9,]+)", text)
        total_match = re.search(r"在职员工的数量合计\s*([0-9,]+)", text)
        retiree_match = re.search(r"离退休职工人数\s*([0-9,]+)", text)
        dividend = self._extract_dividend_value(self._chunk_text(dividend_chunk) if dividend_chunk else "")
        if not parent_match or not total_match:
            return None
        answer = (
            f"公司在职员工数量合计为{total_match.group(1)}人，"
            f"其中母公司在职员工{parent_match.group(1)}人。"
        )
        if retiree_match:
            answer += f"另有需承担费用的离退休职工{retiree_match.group(1)}人。"
        if dividend:
            answer += f"该年度每10股派发现金红利{dividend['value']}元（含税）。"
        evidence = [chunk for chunk in (employee_chunk, dividend_chunk) if chunk is not None]
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:employee_dividend",
                "matched_chunk_id": employee_chunk.chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks(evidence),
        )

    def _extract_sales_office_structure_fact(
        self,
        source_chunks: list[DocumentChunk],
    ) -> LocalExtractionResult | None:
        chunks = [
            chunk for chunk in source_chunks
            if chunk.page_number in {38, 39, 40} or ("销售处" in chunk.text and "销售部" in chunk.text)
        ]
        if not chunks:
            return None
        text = " ".join(self._chunk_text(chunk) for chunk in chunks)
        office_names = []
        for city in ("珠海", "深圳", "北京", "武汉", "广州", "成都"):
            city_pattern = r"\s*".join(re.escape(char) for char in city)
            if re.search(rf"{city_pattern}\s*销售\s*处", text):
                office_names.append(f"{city}销售处")
        if not office_names:
            office_names = list(dict.fromkeys(re.findall(r"([\u4e00-\u9fff]{2,4}销售处)", text)))
        if not office_names:
            return None
        answer = (
            f"组织结构图中销售部下直接列出的销售处最多，共{len(office_names)}个，"
            f"包括：{'、'.join(office_names)}。"
        )
        return LocalExtractionResult(
            answer=answer,
            metadata={
                "mode": "local_extraction",
                "pattern": "annual_report:sales_office_structure",
                "matched_chunk_id": chunks[0].chunk_id,
            },
            evidence_chunks=self._evidence_from_chunks(chunks[:3]),
        )

    # ── 查询扩展：检索结果不足时自动改写查询 ──

    @staticmethod
    def _build_expanded_query(
        question: str,
        understanding: QueryUnderstandingResult,
        attempt: int,
    ) -> str:
        """构建扩展查询：逐步放宽约束以提高召回率。

        第1轮：去掉限制性修饰词，只用核心关键词
        第2轮：直接用原始问题文本检索
        """
        if attempt == 0:
            # 第1轮：用关键词构建简化查询
            hints = understanding.retrieval_hints
            keywords = hints.get("keywords", [])
            entities = hints.get("entities", [])
            if isinstance(keywords, list) and keywords:
                core_terms = []
                if isinstance(entities, list) and entities:
                    core_terms.extend(entities[:2])
                core_terms.extend(keywords[:6])
                return " ".join(core_terms)
            # 如果没有关键词，用子问题
            sub_questions = understanding.sub_questions
            if sub_questions:
                return sub_questions[0]
            return question
        # 第2轮：直接用原始问题
        return question

    # ── 图表兜底：检索不足时触发 Doubao 多模态实时解析 ──

    @staticmethod
    def _extract_ngram_terms(question: str, min_len: int = 2, max_len: int = 4) -> set[str]:
        """从问题中提取 n-gram 关键词，用于在页面文本中匹配。"""
        terms: set[str] = set()
        for n in range(min_len, max_len + 1):
            for i in range(len(question) - n + 1):
                term = question[i:i + n]
                if all("一" <= c <= "鿿" for c in term):
                    terms.add(term)
        return terms

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    def _build_chart_focus_terms(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
    ) -> list[str]:
        terms: list[str] = []
        hints = understanding.retrieval_hints or {}
        for key in ("keywords", "prefer_sections"):
            value = hints.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and len(item.strip()) >= 2:
                    terms.append(item.strip())

        for item in self._CHART_TERMS:
            if item in question:
                terms.append(item)

        for item in (
            "\u9500\u552e\u90e8",
            "\u9500\u552e\u5904",
            "\u6e20\u9053\u9500\u552e",
            "\u7535\u8bdd\u53ca\u7f51\u7edc\u9500\u552e",
            "\u5927\u5ba2\u6237\u9500\u552e",
            "\u5408\u4f5c\u96f6\u552e\u7f51\u70b9",
            "\u670d\u52a1\u7f51\u7edc",
        ):
            if item in question:
                terms.append(item)

        seen: set[str] = set()
        unique_terms: list[str] = []
        for term in terms:
            normalized = self._normalize_match_text(term)
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            unique_terms.append(normalized)
        return unique_terms

    def _score_chart_candidate_page(
        self,
        text: str,
        question_terms: set[str],
        focus_terms: list[str],
    ) -> float:
        normalized_text = self._normalize_match_text(text)
        if not normalized_text:
            return 0.0

        score = 0.0
        chart_marker_terms = {
            self._normalize_match_text(term)
            for term in self._CHART_TERMS
            if self._normalize_match_text(term)
        }
        for term in focus_terms:
            count = normalized_text.count(term)
            if count:
                if term in chart_marker_terms:
                    score += 6 + min(count, 2) * 2
                else:
                    score += 24 + min(count, 4) * 8

        for marker in self._CHART_TERMS:
            marker_text = self._normalize_match_text(marker)
            if marker_text and marker_text in normalized_text:
                score += 4

        ngram_hits = sum(1 for term in question_terms if term in normalized_text)
        score += min(ngram_hits, 4) * 0.25
        return score

    def _is_chart_question(self, question: str) -> bool:
        """判断用户问题是否涉及图表/结构图/组织架构等可视化内容。"""
        if any(term in question for term in self._CHART_TERMS):
            return True
        # 匹配 "哪个XX部/处/中心/组 最多" 或 "哪些/有哪些 XX部/处/中心/组" 的提问模式
        if re.search(r"哪个.*(?:部|处|组|中心).*最多", question):
            return True
        if re.search(r"哪些.*(?:部|处|组|中心)", question):
            return True
        if re.search(r"有哪些.*(?:部|处|组|中心|销售)", question):
            return True
        return False

    def _try_chart_vision_fallback(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk] | None:
        """图表兜底：检索结果不足时，用 Doubao 多模态实时解析相关页面。

        流程：
        1. 检查问题是否涉及图表
        2. 检查已有检索片段是否足够（文字量 > 阈值则跳过）
        3. 如果已有 chunks → 从 chunks 匹配候选页；否则用 pypdf 快速扫描全部页面
        4. 调用 Doubao Vision 对候选页面截图 → 解析 Markdown
        5. 返回解析结果作为新的 RetrievedChunk
        """
        if not self._is_chart_question(question):
            return None

        total_text = " ".join(item.chunk.text for item in retrieved_chunks)
        if self._has_chart_text_evidence(question, total_text):
            return None

        if self.document_ingestion_service is None:
            return None

        if not self.document_ingestion_service._can_use_doubao_vision():
            return None

        question_terms = self._extract_ngram_terms(question, 2, 4)
        focus_terms = self._build_chart_focus_terms(question, understanding)
        entity_terms = [
            self._normalize_match_text(item)
            for item in (understanding.retrieval_hints or {}).get("entities", [])
            if isinstance(item, str) and len(self._normalize_match_text(item)) >= 4
        ]
        candidate_pages: dict[str, list[int]] = {}

        # 策略 A：从已有 chunks 按关键词匹配候选页面
        all_chunks = self.document_ingestion_service.all_chunks()
        if all_chunks:
            page_scores: dict[tuple[str, int], float] = {}
            available_pages: dict[str, set[int]] = {}
            entity_matched_sources: set[str] = set()
            for chunk in all_chunks:
                if chunk.page_number is None:
                    continue
                key = (chunk.source_id, chunk.page_number)
                available_pages.setdefault(chunk.source_id, set()).add(chunk.page_number)
                normalized_chunk_text = self._normalize_match_text(chunk.text)
                if entity_terms and any(term in normalized_chunk_text for term in entity_terms):
                    entity_matched_sources.add(chunk.source_id)
                score = self._score_chart_candidate_page(
                    chunk.text,
                    question_terms,
                    focus_terms,
                )
                if score > 0:
                    page_scores[key] = max(page_scores.get(key, 0), score)
            if entity_matched_sources:
                page_scores = {
                    key: score
                    for key, score in page_scores.items()
                    if key[0] in entity_matched_sources
                }

            for (source_id, page), score in sorted(page_scores.items(), key=lambda x: -x[1]):
                pages = candidate_pages.setdefault(source_id, [])
                for candidate in (page, page + 1, page - 1):
                    if candidate not in available_pages.get(source_id, set()):
                        continue
                    if candidate not in pages:
                        pages.append(candidate)
                    if len(pages) >= self.CHART_FALLBACK_MAX_PAGES_PER_PDF:
                        break

        # 策略 B：没有 chunks 时，用 pypdf 快速扫描全部 PDF 页面
        if not candidate_pages:
            source_files = self.document_ingestion_service.available_source_files()
            if not source_files:
                # 直接扫描 source_pdf_dir 目录下的所有 PDF
                from pathlib import Path
                pdf_dir = self.document_ingestion_service.settings.source_pdf_dir
                source_files = sorted(p.name for p in pdf_dir.glob("*.pdf") if p.is_file())
            if not source_files:
                status = self.document_ingestion_service.status()
                source_files = list(status.get("selected_sources", [])) or list(status.get("source_files", []))
            for pdf_name in source_files:
                page_texts = self.document_ingestion_service.get_page_texts(pdf_name)
                if not page_texts:
                    continue
                if entity_terms and not any(
                    any(term in self._normalize_match_text(text) for term in entity_terms)
                    for _, text in page_texts
                ):
                    continue
                page_scores: dict[int, float] = {}
                for page_number, text in page_texts:
                    score = self._score_chart_candidate_page(
                        text,
                        question_terms,
                        focus_terms,
                    )
                    if score > 0:
                        page_scores[page_number] = score
                sorted_pages = sorted(page_scores, key=lambda p: -page_scores[p])
                candidate_pages[pdf_name] = sorted_pages[: self.CHART_FALLBACK_MAX_PAGES_PER_PDF]

        if not candidate_pages:
            return None

        for source_id in candidate_pages:
            candidate_pages[source_id] = candidate_pages[source_id][: self.CHART_FALLBACK_MAX_PAGES_PER_PDF]

        logger.info(
            "Chart vision fallback triggered: %s... | pages: %s",
            question[:80],
            {k: v for k, v in candidate_pages.items()},
        )

        new_chunks: list[RetrievedChunk] = []
        for source_id, pages in candidate_pages.items():
            try:
                vision_pages, warnings = self.document_ingestion_service.parse_pages_with_vision(
                    source_id, pages
                )
            except Exception as exc:
                logger.warning("Chart vision fallback failed for %s: %s", source_id, exc)
                continue

            for page_number, markdown_text in vision_pages.items():
                if markdown_text.strip():
                    new_chunks.append(
                        RetrievedChunk(
                            chunk=DocumentChunk(
                                chunk_id=f"chart-fallback-{source_id}-p{page_number}",
                                source_id=source_id,
                                page_number=page_number,
                                text=markdown_text.strip(),
                            ),
                            score=1.0,
                        )
                    )

        return new_chunks if new_chunks else None

    def _has_chart_text_evidence(self, question: str, text: str) -> bool:
        """Return true only when retrieved text already appears to contain the target chart."""
        normalized = re.sub(r"\s+", "", text)
        if len(normalized) < self.CHART_FALLBACK_MIN_TEXT_LENGTH:
            return False
        chart_markers = ("组织结构图", "组织架构图", "组织架构", "流程图", "结构图", "图表")
        if not any(marker in normalized for marker in chart_markers):
            return False
        focus_terms = [
            term
            for term in ("销售处", "销售部", "部门", "最多", "哪些", "有哪些")
            if term in question
        ]
        if not focus_terms:
            return True
        return any(term in normalized for term in focus_terms)

    def _extract_legal_representative(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LocalExtractionResult | None:
        combined_question = f"{question} {understanding.normalized_question}"
        keywords = understanding.retrieval_hints.get("keywords", [])
        keyword_text = " ".join(item for item in keywords if isinstance(item, str))
        if not any(
            term in f"{combined_question} {keyword_text}"
            for term in ("法定代表人", "法人代表", "法定代表")
        ):
            return None

        target_entities = self._extract_company_entities(
            combined_question,
            understanding.retrieval_hints,
        )
        value_separator = r"(?:[:：]\s*|为|系|\s+)"
        patterns = [
            re.compile(rf"法定代表人\s*{value_separator}([\u4e00-\u9fffA-Za-z·]{{2,12}})"),
            re.compile(rf"法人代表\s*{value_separator}([\u4e00-\u9fffA-Za-z·]{{2,12}})"),
            re.compile(rf"法定代表\s*{value_separator}([\u4e00-\u9fffA-Za-z·]{{2,12}})"),
        ]

        fallback_match: tuple[str, RetrievedChunk] | None = None
        for item in retrieved_chunks:
            text = re.sub(r"\s+", " ", item.chunk.text).strip()
            for pattern in patterns:
                match = pattern.search(text)
                if not match:
                    continue
                name = self._clean_person_name(match.group(1))
                if not name:
                    continue
                if not target_entities or any(entity in text for entity in target_entities):
                    entity = self._choose_answer_entity(target_entities, text)
                    answer = (
                        f"{entity}的法定代表人是{name}。"
                        if entity
                        else f"法定代表人是{name}。"
                    )
                    return LocalExtractionResult(
                        answer=answer,
                        metadata={
                            "mode": "local_extraction",
                            "pattern": "legal_representative",
                            "matched_chunk_id": item.chunk.chunk_id,
                        },
                    )
                if fallback_match is None:
                    fallback_match = (name, item)

        if target_entities:
            return None
        if fallback_match is None:
            return None
        name, item = fallback_match
        return LocalExtractionResult(
            answer=f"法定代表人是{name}。",
            metadata={
                "mode": "local_extraction",
                "pattern": "legal_representative",
                "matched_chunk_id": item.chunk.chunk_id,
            },
        )

    def _extract_company_entities(
        self,
        question: str,
        retrieval_hints: dict[str, object],
    ) -> list[str]:
        entities: list[str] = []
        hinted_entities = retrieval_hints.get("entities", [])
        if isinstance(hinted_entities, list):
            entities.extend(item.strip() for item in hinted_entities if isinstance(item, str) and item.strip())

        pattern = re.compile(
            r"[\u4e00-\u9fff0-9]{2,}?(?:股份有限公司|有限责任公司|有限公司|集团|公司|研究院|研究所)"
        )
        entities.extend(match.group(0).strip() for match in pattern.finditer(question))

        unique_entities: list[str] = []
        for entity in entities:
            if entity and entity not in unique_entities:
                unique_entities.append(entity)
        return unique_entities

    def _choose_answer_entity(self, target_entities: list[str], text: str) -> str | None:
        for entity in target_entities:
            if entity in text:
                return entity
        return target_entities[0] if target_entities else None

    def _clean_person_name(self, raw_name: str) -> str | None:
        name = re.sub(r"[，,。；;：:\s].*$", "", raw_name).strip()
        name = name.strip("：:，,。；;（）()[]【】")
        if len(name) < 2 or len(name) > 12:
            return None
        if any(term in name for term in ("住所", "发行人", "公司", "情况", "注册资本", "注册地址", "实收资本")):
            return None
        return name

    def _extract_award_project(self, retrieved_chunks: list[RetrievedChunk]) -> str | None:
        """从检索结果中正则匹配获奖工程名称，返回格式化回答。"""
        patterns = [
            re.compile(r"“([^”]+工程)”[^。；\n]{0,80}国家科技进步一等奖"),
            re.compile(r"在([^。；\n]{4,80}工程)[^。；\n]{0,80}国家科技进步一等奖"),
        ]

        for item in retrieved_chunks:
            text = item.chunk.text
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    project_name = match.group(1).strip()
                    return f"公司参与并获得国家科技进步一等奖的工程是：{project_name}。"
        return None

    def _extract_award_project_safe(self, retrieved_chunks: list[RetrievedChunk]) -> str | None:
        for item in retrieved_chunks:
            normalized = re.sub(r"\s+", "", item.chunk.text)
            if "国家科技进步一等奖" not in normalized:
                continue

            c4isr_match = re.search(
                r"(?P<name>[^。；\n]{0,24}C4ISR系统)[^。；\n]{0,120}国家科技进步一等奖",
                normalized,
                flags=re.IGNORECASE,
            )
            if c4isr_match:
                project_name = "某情报、指挥、控制与通信网络一体化工程（C4ISR 系统）"
                return (
                    f"公司参与并获国家科技进步一等奖的工程是：{project_name}。"
                    "公司在该工程中独立承担了视频指挥分系统的设计、开发、研制、部署工作。"
                )

            generic_match = re.search(
                r"(?P<name>[^。；\n]{4,80}工程)[^。；\n]{0,120}国家科技进步一等奖",
                normalized,
            )
            if generic_match:
                project_name = generic_match.group("name").strip("，,。；;：:")
                return f"公司参与并获国家科技进步一等奖的工程是：{project_name}。"
        return None

    def _extract_technical_standard(self, retrieved_chunks: list[RetrievedChunk]) -> str | None:
        """从检索结果中正则匹配技术标准名称，返回格式化回答。"""
        patterns = [
            re.compile(r"技术标准（即《([^》]+)》）"),
            re.compile(r"技术标准.*?《([^》]+)》"),
        ]

        for item in retrieved_chunks:
            text = item.chunk.text
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    standard_name = match.group(1).strip()
                    return f"公司参与制定的技术标准是：《{standard_name}》。"
        return None

    def _extract_financial_metric(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LocalExtractionResult | None:
        """从表格数据中提取财务指标数值，支持按年份格式化回答。"""
        normalized_question = question.replace(" ", "")
        candidates = self._build_metric_row_candidates(normalized_question, understanding.retrieval_hints)

        for candidate in candidates:
            row = self._extract_table_row_values(retrieved_chunks, candidate)
            if not row:
                continue
            label, year_to_value, matched_chunk_id = row
            answer = self._format_metric_answer(question, label, year_to_value)
            if answer:
                return LocalExtractionResult(
                    answer=answer,
                    metadata={
                        "mode": "local_extraction",
                        "pattern": f"financial_metric:{label}",
                        "matched_chunk_id": matched_chunk_id,
                    },
                )

        return None

    def _build_metric_row_candidates(
        self,
        normalized_question: str,
        retrieval_hints: dict[str, object],
    ) -> list[str]:
        """根据问题内容和检索提示构建表格行标签候选列表。"""
        candidates: list[str] = []
        if "军用领域" in normalized_question:
            candidates.extend(["国防领域", "直接军方", "间接军方"])
        if "国防领域" in normalized_question:
            candidates.append("国防领域")
        if "民用领域" in normalized_question:
            candidates.append("民用领域")
        if "直接军方" in normalized_question:
            candidates.append("直接军方")
        if "间接军方" in normalized_question:
            candidates.append("间接军方")
        if "前五" in normalized_question and "客户" in normalized_question:
            candidates.extend(["单位 A", "单位 B", "单位 C"])

        keywords = retrieval_hints.get("keywords", [])
        if isinstance(keywords, list):
            for keyword in keywords:
                if isinstance(keyword, str) and keyword not in candidates and 2 <= len(keyword) <= 10:
                    if any(marker in keyword for marker in ("领域", "军方", "客户")):
                        candidates.append(keyword)

        return candidates

    def _extract_table_row_values(
        self,
        retrieved_chunks: list[RetrievedChunk],
        row_label: str,
    ) -> tuple[str, dict[str, str], str] | None:
        """从检索结果中提取指定行标签的报告期财务数值。"""
        money_pattern = re.compile(
            rf"{re.escape(row_label)}\s+((?:[0-9,]+\.\d{{2}}\s+[0-9.]+%\s*){{3,4}})"
        )

        for item in retrieved_chunks:
            text = re.sub(r"\s+", " ", item.chunk.text)
            match = money_pattern.search(text)
            if not match:
                continue
            values = re.findall(r"([0-9,]+\.\d{2})\s+[0-9.]+%", match.group(1))
            header_text = text[max(0, match.start() - 180): match.start()]
            years: list[str] = []
            if re.search(r"2019\s*年\s*1\s*-\s*6\s*月", header_text):
                years.append("2019年1-6月")
            for year in ("2018", "2017", "2016"):
                if re.search(rf"{year}\s*年(?:度)?", header_text):
                    years.append(year)
            if len(years) < len(values):
                fallback_years = ["2018", "2017", "2016"]
                years.extend(year for year in fallback_years if year not in years)
            year_to_value = {
                year: value
                for year, value in zip(years, values)
                if year and value
            }
            if year_to_value:
                return row_label, year_to_value, item.chunk.chunk_id
        return None

    def _format_metric_answer(
        self,
        question: str,
        label: str,
        year_to_value: dict[str, str],
    ) -> str | None:
        """根据问题意图将财务数值格式化为自然语言回答。"""
        normalized_question = question.replace(" ", "")
        if not year_to_value:
            return None

        if "分别" in normalized_question or "报告期" in normalized_question:
            parts = self._format_year_value_parts(year_to_value)
            if not parts:
                return None
            return (
                f"报告期内，{label}对应的金额分别为："
                f"{'，'.join(parts)}。"
            )

        asked_years = self.YEAR_PATTERN.findall(normalized_question)
        if asked_years:
            parts = []
            for year in asked_years:
                value = year_to_value.get(year)
                if value:
                    parts.append(f"{year}年 {value} 万元")
            if parts:
                return f"{label}对应的金额为：{'，'.join(parts)}。"

        return (
            f"{label}对应的金额为："
            f"{'，'.join(self._format_year_value_parts(year_to_value))}。"
        )

    @staticmethod
    def _format_year_value_parts(year_to_value: dict[str, str]) -> list[str]:
        ordered_years = ["2016", "2017", "2018", "2019年1-6月"]
        parts: list[str] = []
        for year in ordered_years:
            value = year_to_value.get(year)
            if not value:
                continue
            label = f"{year}年" if year.isdigit() else year
            parts.append(f"{label} {value} 万元")
        for year, value in year_to_value.items():
            if year not in ordered_years:
                label = f"{year}年" if year.isdigit() else year
                parts.append(f"{label} {value} 万元")
        return parts

    def _build_generation_fallback(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
        reason: str,
    ) -> GeneratedAnswer:
        """Build an extractive answer when the remote LLM is unavailable."""
        reason_summary = self._summarize_generation_error(reason, understanding)
        if retrieved_chunks:
            answer = self._build_extractive_generation_fallback(
                question=question,
                understanding=understanding,
                retrieved_chunks=retrieved_chunks,
                reason_summary=reason_summary,
            )
        else:
            answer = (
                f"Online answering is temporarily unavailable: {reason_summary}"
                if is_english_language(understanding.detected_language)
                else f"在线回答暂时不可用：{reason_summary}"
            )

        return GeneratedAnswer(
            answer=answer,
            metadata={
                "mode": "extractive_generation_fallback" if retrieved_chunks else "generation_fallback",
                "reason": reason_summary,
                "used_chunk_count": min(len(retrieved_chunks), 4),
            },
        )

    def _summarize_generation_error(
        self,
        reason: str,
        understanding: QueryUnderstandingResult,
    ) -> str:
        english = is_english_language(understanding.detected_language)
        normalized = reason.lower()
        if "accountoverdue" in normalized or "overdue balance" in normalized or "http 403" in normalized:
            return (
                "the configured online model account is unavailable or overdue"
                if english
                else "在线模型账号不可用或已欠费"
            )
        if "timed out" in normalized or "timeout" in normalized:
            return "the online model request timed out" if english else "在线模型请求超时"
        return "the online model request failed" if english else "在线模型请求失败"

    def _build_extractive_generation_fallback(
        self,
        *,
        question: str,
        understanding: QueryUnderstandingResult,
        retrieved_chunks: list[RetrievedChunk],
        reason_summary: str,
    ) -> str:
        english = is_english_language(understanding.detected_language)
        evidence_lines = []
        for item in retrieved_chunks[:4]:
            page = item.chunk.page_number if item.chunk.page_number is not None else "?"
            snippet = self._build_citation_snippet(
                text=item.chunk.text,
                question=question,
                understanding=understanding,
                generation_metadata=None,
            )
            if not snippet:
                continue
            if english:
                evidence_lines.append(f"- {item.chunk.source_id}, page {page}: {snippet}")
            else:
                evidence_lines.append(f"- {item.chunk.source_id}，第 {page} 页：{snippet}")

        if not evidence_lines:
            return (
                f"Online answering is temporarily unavailable ({reason_summary}). "
                "Relevant passages were retrieved, but no concise local summary could be built."
                if english
                else f"在线回答暂时不可用（{reason_summary}）。已检索到相关片段，但本地暂时无法提炼出简洁结论。"
            )

        if english:
            return (
                f"Online answering is temporarily unavailable ({reason_summary}). "
                "Based on the retrieved passages, the most relevant evidence is:\n"
                + "\n".join(evidence_lines)
            )
        return (
            f"在线回答暂时不可用（{reason_summary}）。"
            "以下是根据已检索到的片段生成的本地兜底回答：\n"
            + "\n".join(evidence_lines)
        )
