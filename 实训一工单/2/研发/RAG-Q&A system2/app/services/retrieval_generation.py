"""
检索与生成服务模块
==================
负责将用户问题经向量检索、可选重排序后，交给 LLM 生成最终回答，
并构建引用（Citation）返回给前端。

核心流程：检索 → 重排序 → 本地精准提取 / LLM 生成 → 引用构建 → 返回结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import re
import uuid

from app.schemas.query import Citation, QueryResponse, QueryUnderstandingResult
from app.services.llm.base import BaseLLMClient, GeneratedAnswer
from app.services.llm.openai_compatible import LLMRemoteError
from app.services.reranker import RerankerService
from app.services.retrievers.base import BaseRetriever, RetrievedChunk


@dataclass
class LocalExtractionResult:
    """本地精准提取的结果封装。

    Attributes:
        answer: 提取到的回答文本。
        metadata: 提取过程的元数据（如提取模式、匹配到的行标签等）。
    """
    answer: str
    metadata: dict[str, object]


class RetrievalGenerationService:
    """检索与生成服务。

    整合向量检索器、重排序器和 LLM 客户端，提供一站式的问答能力。
    支持三种本地精准提取意图（获奖工程、技术标准、财务指标），
    无法本地提取时回退到 LLM 生成。
    """
    YEAR_PATTERN = re.compile(r"(20\d{2})")
    MONEY_PATTERN = re.compile(r"[0-9][0-9,]*\.\d{2}")

    def __init__(
        self,
        retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        default_top_k: int,
        reranker: RerankerService | None = None,
    ) -> None:
        """初始化服务，注入检索器、LLM 客户端和可选的重排序器。"""
        self.retriever = retriever
        self.llm_client = llm_client
        self.default_top_k = default_top_k
        self.reranker = reranker

    def prepare_retrieval(self, selected_only: bool = False) -> None:
        """预加载/构建向量索引，为后续检索做准备。"""
        self.retriever.prepare(selected_only=selected_only)

    def answer(
        self,
        question: str,
        understanding: QueryUnderstandingResult,
        top_k: int | None = None,
        include_debug: bool = False,
        timing: dict[str, float] | None = None,
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> QueryResponse:
        """核心方法：执行检索 → 重排序 → 生成 → 构建引用，返回完整回答。"""
        resolved_top_k = top_k or self.default_top_k
        retrieval_started_at = perf_counter()
        retrieved_chunks = self.retriever.retrieve(
            question=understanding.normalized_question,
            top_k=resolved_top_k,
            retrieval_hints=understanding.retrieval_hints,
        )
        if self.reranker and retrieved_chunks:
            retrieved_chunks = self.reranker.rerank(
                question=understanding.normalized_question,
                chunks=retrieved_chunks,
            )
        retrieval_elapsed_ms = round((perf_counter() - retrieval_started_at) * 1000, 2)

        generation_started_at = perf_counter()
        generation_error: str | None = None
        generated: GeneratedAnswer

        # 优先尝试本地精准提取，避免不必要的 LLM 调用
        local_extraction = self._try_local_extraction(question, understanding, retrieved_chunks)
        if local_extraction is not None:
            generated = GeneratedAnswer(
                answer=local_extraction.answer,
                metadata=local_extraction.metadata,
            )
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
                generated = self._build_generation_fallback(generation_error)

        generation_elapsed_ms = round((perf_counter() - generation_started_at) * 1000, 2)

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
                "timing_ms": {
                    **(timing or {}),
                    "retrieval": retrieval_elapsed_ms,
                    "generation": generation_elapsed_ms,
                },
            }
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

        if understanding.intent == "award_project":
            extracted = self._extract_award_project(retrieved_chunks)
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
            label, year_to_value = row
            answer = self._format_metric_answer(question, label, year_to_value)
            if answer:
                return LocalExtractionResult(
                    answer=answer,
                    metadata={"mode": "local_extraction", "pattern": f"financial_metric:{label}"},
                )

        fundraising_amount = self._extract_fundraising_usage_amount(question, retrieved_chunks)
        if fundraising_amount is not None:
            return fundraising_amount

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
    ) -> tuple[str, dict[str, str]] | None:
        """从检索结果中提取指定行标签的三年财务数值（2016-2018）。"""
        money_pattern = re.compile(
            rf"{re.escape(row_label)}\s+([0-9,]+\.\d{{2}})\s+[0-9.]+%\s+([0-9,]+\.\d{{2}})\s+[0-9.]+%\s+([0-9,]+\.\d{{2}})\s+[0-9.]+%"
        )

        for item in retrieved_chunks:
            text = re.sub(r"\s+", " ", item.chunk.text)
            match = money_pattern.search(text)
            if not match:
                continue
            value_2018, value_2017, value_2016 = match.groups()
            return row_label, {
                "2016": value_2016,
                "2017": value_2017,
                "2018": value_2018,
            }
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
            return (
                f"报告期内，{label}对应的金额分别为："
                f"2016年 {year_to_value.get('2016', '未知')} 万元，"
                f"2017年 {year_to_value.get('2017', '未知')} 万元，"
                f"2018年 {year_to_value.get('2018', '未知')} 万元。"
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
            f"2016年 {year_to_value.get('2016', '未知')} 万元，"
            f"2017年 {year_to_value.get('2017', '未知')} 万元，"
            f"2018年 {year_to_value.get('2018', '未知')} 万元。"
        )

    def _extract_fundraising_usage_amount(
        self,
        question: str,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LocalExtractionResult | None:
        normalized_question = question.replace(" ", "")
        if not any(term in normalized_question for term in ("募集资金", "募资", "募投")):
            return None
        if not any(term in normalized_question for term in ("补充流动资金", "流动资金")):
            return None

        label_candidates = ("补充流动资金", "补充公司流动资金")
        patterns = [
            r"{label}[^\d]{{0,20}}([0-9][0-9,]*(?:\.\d+)?)\s*(亿元|万元|元)",
            r"([0-9][0-9,]*(?:\.\d+)?)\s*(亿元|万元|元)[^。\n；;]{{0,20}}{label}",
        ]

        for item in retrieved_chunks:
            text = re.sub(r"\s+", " ", item.chunk.text)
            for label in label_candidates:
                for template in patterns:
                    pattern = re.compile(template.format(label=re.escape(label)))
                    match = pattern.search(text)
                    if not match:
                        continue

                    amount, unit = match.group(1), match.group(2)
                    return LocalExtractionResult(
                        answer=f"本次发行募集资金中，用于补充流动资金的金额为 {amount} {unit}。",
                        metadata={
                            "mode": "local_extraction",
                            "pattern": "financial_metric:补充流动资金",
                        },
                    )

        return None

    def _build_generation_fallback(self, reason: str) -> GeneratedAnswer:
        """LLM 调用失败时的兜底回答。"""
        return GeneratedAnswer(
            answer=f"在线回答暂时不可用：{reason}",
            metadata={
                "mode": "generation_fallback",
                "reason": reason,
            },
        )
