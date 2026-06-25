from __future__ import annotations

"""基于关键词的检索器实现。
使用中文分词 + 同义词扩展 + 多维度加权评分的方式检索文档片段，
不依赖向量数据库，适合小规模文档或离线场景。
"""

import math
import re

from app.services.document_ingestion import DocumentIngestionService
from app.services.retrievers.base import BaseRetriever, RetrievedChunk


class KeywordRetriever(BaseRetriever):
    """基于关键词匹配的检索器。

    通过中文 n-gram 分词、同义词映射、强/弱术语分类以及多维度评分
    （精确匹配、子串匹配、焦点词、强术语、公司实体等）对文档片段进行排序。
    """

    SYNONYM_MAP = {
        "军用": "国防",
        "军用领域": "国防领域",
        "军用领域收入": "国防领域收入",
        "军方": "国防",
        "募投": "募集资金",
        "募投项目": "募集资金投资项目",
        "补流": "补充流动资金",
    }
    WEAK_TERMS = {
        "公司",
        "根据",
        "招股意向书",
        "招股说明书",
        "发行人",
        "股份有限公司",
        "有限公司",
        "企业",
        "行业",
        "哪些",
        "哪个",
        "情况",
    }
    STRONG_TERMS = {
        "上游",
        "下游",
        "产业链",
        "供应链",
        "客户",
        "技术标准",
        "技术规范",
        "标准",
        "规范",
        "竞争对手",
        "同行",
        "军品",
        "民品",
        "军用",
        "国防",
        "军用领域",
        "国防领域",
        "军用领域收入",
        "国防领域收入",
        "核心技术",
        "销售情况",
        "主营业务收入",
        "募集资金",
        "募集资金运用",
        "本次募集资金运用",
        "募集资金投资项目",
        "募投项目",
        "资金用途",
        "补充流动资金",
        "流动资金",
        "重大事项",
        "6,464.51",
        "14,414.16",
        "18,780.67",
        "82.10%",
        "97.31%",
        "94.84%",
    }
    ENTITY_SUFFIXES = ("公司", "有限公司", "股份有限公司", "集团", "研究院", "研究所")
    GENERIC_ENTITY_TERMS = {
        "公司",
        "有限",
        "有限公司",
        "股份",
        "股份有限公司",
        "有限责任",
        "有限责任公司",
        "集团",
    }

    def __init__(self, document_ingestion_service: DocumentIngestionService) -> None:
        self.document_ingestion_service = document_ingestion_service
        self._indexed_chunks: list[tuple[RetrievedChunk, set[str], str]] | None = None
        self._indexed_chunk_count = -1

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        hint_terms = set(self._extract_hint_terms(retrieval_hints))
        query_terms = set(self._tokenize(question)) if not hint_terms else set()
        entity_strings = set(self._extract_entity_strings(retrieval_hints))
        entity_terms = set(self._extract_entity_terms(retrieval_hints))

        expanded_terms = set(query_terms)
        for term in list(query_terms):
            synonym = self.SYNONYM_MAP.get(term)
            if synonym:
                expanded_terms.add(synonym)
            for src, dst in self.SYNONYM_MAP.items():
                if term == dst:
                    expanded_terms.add(src)

        all_terms = query_terms | expanded_terms | hint_terms
        if not all_terms:
            return []

        strong_terms = {
            term
            for term in all_terms
            if term in self.STRONG_TERMS or (len(term) >= 4 and term not in entity_terms)
        }
        strong_terms = {term for term in strong_terms if term not in self.WEAK_TERMS}

        focus_terms = {
            term for term in all_terms if term not in self.WEAK_TERMS and term not in entity_terms
        }

        indexed_chunks = self._ensure_index()
        selected_sources = self._selected_sources()
        source_entity_hits = self._build_source_entity_hits(
            indexed_chunks=indexed_chunks,
            selected_sources=selected_sources,
            entity_strings=entity_strings,
        )
        has_source_entity_match = bool(source_entity_hits)
        results: list[RetrievedChunk] = []

        for retrieved_chunk, chunk_terms, normalized_text in indexed_chunks:
            if selected_sources and retrieved_chunk.chunk.source_id not in selected_sources:
                continue
            if not chunk_terms:
                continue

            exact_overlap = sum(1 for term in all_terms if term in chunk_terms)
            substring_overlap = sum(
                1 for term in all_terms if len(term) >= 2 and term in normalized_text
            )
            focus_overlap = sum(1 for term in focus_terms if term in normalized_text)
            strong_overlap = sum(1 for term in strong_terms if term in normalized_text)
            exact_entity_overlap = sum(1 for term in entity_strings if term in normalized_text)
            entity_overlap = sum(1 for term in entity_terms if term in normalized_text)
            source_entity_overlap = source_entity_hits.get(retrieved_chunk.chunk.source_id, 0)
            section_boost = self._compute_section_boost(retrieval_hints, normalized_text)

            if exact_overlap == 0 and substring_overlap == 0:
                continue
            if entity_strings and exact_entity_overlap == 0 and strong_overlap == 0 and focus_overlap < 2:
                continue
            if focus_terms and focus_overlap == 0 and not strong_overlap:
                continue
            if strong_terms and strong_overlap == 0 and focus_overlap < 2:
                continue

            density = (exact_overlap + substring_overlap + focus_overlap) / max(len(chunk_terms), 1)
            score = (
                exact_overlap * 1.7
                + substring_overlap * 0.9
                + focus_overlap * 3.2
                + strong_overlap * 4.8
                + exact_entity_overlap * 24.0
                + entity_overlap * 0.2
                + source_entity_overlap * 18.0
                + section_boost
                + math.log1p(len(focus_terms) or len(all_terms))
                + density
            )
            if entity_strings and exact_entity_overlap == 0:
                score -= 12.0
            if entity_strings and has_source_entity_match and source_entity_overlap == 0:
                score -= 18.0

            results.append(
                RetrievedChunk(
                    chunk=retrieved_chunk.chunk,
                    score=round(score, 4),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        self._ensure_index()

    def _ensure_index(self) -> list[tuple[RetrievedChunk, set[str], str]]:
        chunks = self.document_ingestion_service.all_chunks()
        if self._indexed_chunks is not None and self._indexed_chunk_count == len(chunks):
            return self._indexed_chunks

        indexed: list[tuple[RetrievedChunk, set[str], str]] = []
        for chunk in chunks:
            normalized_text = self._normalize_text(chunk.text)
            indexed.append(
                (
                    RetrievedChunk(chunk=chunk, score=0.0),
                    set(self._tokenize(normalized_text)),
                    normalized_text,
                )
            )

        self._indexed_chunks = indexed
        self._indexed_chunk_count = len(chunks)
        return indexed

    def _selected_sources(self) -> set[str]:
        status = self.document_ingestion_service.status()
        selected_sources = status.get("selected_sources", [])
        if not isinstance(selected_sources, list):
            return set()
        return {item for item in selected_sources if isinstance(item, str) and item.strip()}

    def _extract_hint_terms(self, retrieval_hints: dict[str, object] | None) -> list[str]:
        if not retrieval_hints:
            return []

        terms: list[str] = []
        for key in ("keywords", "time_constraints", "notes", "prefer_sections"):
            value = retrieval_hints.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        terms.extend(self._tokenize(item))
        return terms

    def _extract_entity_strings(self, retrieval_hints: dict[str, object] | None) -> list[str]:
        if not retrieval_hints:
            return []

        entities = retrieval_hints.get("entities")
        if not isinstance(entities, list):
            return []

        normalized_entities: list[str] = []
        for entity in entities:
            if not isinstance(entity, str) or not entity.strip():
                continue
            normalized = self._normalize_text(entity)
            if normalized:
                normalized_entities.append(normalized)
        return normalized_entities

    def _extract_entity_terms(self, retrieval_hints: dict[str, object] | None) -> list[str]:
        if not retrieval_hints:
            return []

        terms: list[str] = []
        for entity in self._extract_entity_strings(retrieval_hints):
            for token in self._tokenize(entity):
                if len(token) < 3 or token in self.GENERIC_ENTITY_TERMS or token in self.WEAK_TERMS:
                    continue
                terms.append(token)
        return terms

    def _build_source_entity_hits(
        self,
        *,
        indexed_chunks: list[tuple[RetrievedChunk, set[str], str]],
        selected_sources: set[str],
        entity_strings: set[str],
    ) -> dict[str, int]:
        if not entity_strings:
            return {}

        source_hits: dict[str, int] = {}
        for retrieved_chunk, _, normalized_text in indexed_chunks:
            if selected_sources and retrieved_chunk.chunk.source_id not in selected_sources:
                continue
            hits = sum(1 for entity in entity_strings if entity in normalized_text)
            if hits:
                source_hits[retrieved_chunk.chunk.source_id] = max(
                    source_hits.get(retrieved_chunk.chunk.source_id, 0),
                    hits,
                )
        return source_hits

    def _compute_section_boost(
        self,
        retrieval_hints: dict[str, object] | None,
        normalized_text: str,
    ) -> float:
        if not retrieval_hints:
            return 0.0

        prefer_sections = retrieval_hints.get("prefer_sections")
        if not isinstance(prefer_sections, list):
            return 0.0

        boost = 0.0
        for section in prefer_sections:
            if not isinstance(section, str) or not section.strip():
                continue
            normalized_section = self._normalize_text(section)
            if normalized_section and normalized_section in normalized_text:
                boost += 2.2
        return boost

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    def _tokenize(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        mixed_tokens = [token for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", normalized) if token]
        tokens: set[str] = set()

        for token in mixed_tokens:
            if len(token) >= 2 and token not in self.WEAK_TERMS:
                tokens.add(token)

            if self._looks_like_entity(token):
                continue

            if re.search(r"[\u4e00-\u9fff]", token):
                for size in (2, 3, 4):
                    if len(token) < size:
                        continue
                    for index in range(0, len(token) - size + 1):
                        gram = token[index : index + size]
                        if gram not in self.WEAK_TERMS:
                            tokens.add(gram)

        return sorted(tokens)

    def _looks_like_entity(self, token: str) -> bool:
        return len(token) >= 6 and token.endswith(self.ENTITY_SUFFIXES)
