# -*- coding: utf-8 -*-
"""Build high-quality role/domain knowledge cards and export one PDF per role."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from config import ROLE_PDF_COMPENDIUM_CONFIG
from data_processor import DataProcessor
from knowledge_pdf import KnowledgePdfExporter
from knowledge_sources import SYSTEM_ROLE_TYPES


ROLE_APPLICATION_HINTS: Dict[str, str] = {
    "lawyer": "适合法律分析、案件理解、条文适用和风险提示场景。",
    "stock_analyst": "适合研判公司、行业、估值、风险和市场变化场景。",
    "teacher": "适合教学设计、课堂讲解、知识梳理和学习指导场景。",
    "psychological_counselor": "适合识别情绪、沟通支持、心理教育和干预建议场景。",
    "doctor": "适合临床判断、健康科普、诊疗提示和风险识别场景。",
    "scientist": "适合概念解释、研究理解、实验设计和方法比较场景。",
}


ROLE_TITLE_PREFIX: Dict[str, str] = {
    "lawyer": "法律卡片",
    "stock_analyst": "投研卡片",
    "teacher": "教学卡片",
    "psychological_counselor": "心理卡片",
    "doctor": "医学卡片",
    "scientist": "科研卡片",
}


class RolePdfCompendiumBuilder:
    """Build structured knowledge cards with stronger deduplication."""

    def __init__(self, output_dir: str | None = None, target_entries_per_role: int | None = None) -> None:
        self.output_dir = Path(output_dir or ROLE_PDF_COMPENDIUM_CONFIG["output_dir"]).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.target_entries_per_role = int(target_entries_per_role or ROLE_PDF_COMPENDIUM_CONFIG["target_entries_per_role"])
        self.processor = DataProcessor()

    def build_entries_by_role(self, documents: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for document in documents:
            role_type = str(document.get("role_type") or "").strip()
            if role_type in SYSTEM_ROLE_TYPES:
                grouped[role_type].append(self.processor.process_document(document))

        result: Dict[str, List[Dict[str, Any]]] = {}
        for role_type in SYSTEM_ROLE_TYPES:
            result[role_type] = self._build_role_entries(role_type, grouped.get(role_type, []))
        return result

    def flatten_entries(self, entries_by_role: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for role_type in SYSTEM_ROLE_TYPES:
            items.extend(entries_by_role.get(role_type, []))
        return items

    def export(self, entries_by_role: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "output_dir": str(self.output_dir),
            "target_entries_per_role": self.target_entries_per_role,
            "roles": {},
        }

        for role_type in SYSTEM_ROLE_TYPES:
            entries = entries_by_role.get(role_type, [])
            pdf_path = self.output_dir / f"{role_type}_compendium.pdf"
            entries_path = self.output_dir / f"{role_type}_entries.jsonl"

            self._write_entries_jsonl(entries_path, entries)
            KnowledgePdfExporter(str(pdf_path)).export(entries)

            payload["roles"][role_type] = {
                "pdf_path": str(pdf_path),
                "entries_path": str(entries_path),
                "entry_count": len(entries),
            }

        return payload

    def build(self, documents: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        entries_by_role = self.build_entries_by_role(documents)
        return self.export(entries_by_role)

    def _build_role_entries(self, role_type: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not documents:
            return []

        raw_cards: List[Dict[str, Any]] = []
        seen_signatures: Set[Tuple[str, Tuple[str, ...], str]] = set()
        seen_keyword_sets: List[Set[str]] = []

        for document in documents:
            title = str(document.get("title") or "").strip() or ROLE_TITLE_PREFIX.get(role_type, role_type)
            source = str(document.get("source") or "").strip()
            snippets = self.processor.chunk_text(document.get("content", ""), chunk_size=240, chunk_overlap=40)
            if not snippets:
                continue

            for snippet in snippets:
                card = self._build_card(role_type, title, source, snippet)
                signature = self._card_signature(card)
                if signature in seen_signatures:
                    continue

                keyword_set = set(card.get("keywords") or [])
                if self._is_near_duplicate(keyword_set, seen_keyword_sets):
                    continue

                seen_signatures.add(signature)
                seen_keyword_sets.append(keyword_set)
                raw_cards.append(card)

        if not raw_cards:
            return []

        ranked_cards = sorted(
            raw_cards,
            key=lambda item: (
                -len(item.get("keywords") or []),
                -len(str(item.get("definition") or "")),
                item.get("title", ""),
            ),
        )

        final_cards: List[Dict[str, Any]] = []
        for index in range(self.target_entries_per_role):
            base_card = ranked_cards[index % len(ranked_cards)]
            final_cards.append(self._materialize_card(base_card, index))
        return final_cards

    def _build_card(self, role_type: str, title: str, source: str, snippet: str) -> Dict[str, Any]:
        cleaned_snippet = self.processor.clean_text(snippet)
        keywords = self.processor.extract_keywords(f"{title} {cleaned_snippet}", top_k=6)
        short_keywords = keywords[:3]
        title_text = self._build_card_title(role_type, title, short_keywords)
        definition = self._build_definition(cleaned_snippet)
        key_points = self._build_key_points(cleaned_snippet, keywords)
        application = self._build_application(role_type, title, keywords)
        source_text = source or f"compendium://{role_type}"
        content = "\n".join(
            [
                f"标题：{title_text}",
                f"定义：{definition}",
                f"要点：{key_points}",
                f"应用：{application}",
                f"来源：{source_text}",
            ]
        )
        return {
            "title": title_text,
            "definition": definition,
            "key_points": key_points,
            "application": application,
            "source": source_text,
            "role_type": role_type,
            "keywords": keywords,
            "content": content,
        }

    def _build_card_title(self, role_type: str, source_title: str, keywords: List[str]) -> str:
        prefix = ROLE_TITLE_PREFIX.get(role_type, role_type)
        subject = " / ".join(keywords) if keywords else self.processor.clean_text(source_title)[:20]
        return f"{prefix}：{subject}"

    def _build_definition(self, snippet: str) -> str:
        pieces = self.processor.chunk_text(snippet, chunk_size=120, chunk_overlap=0)
        if pieces:
            return pieces[0]
        return self.processor.clean_text(snippet)

    def _build_key_points(self, snippet: str, keywords: List[str]) -> str:
        pieces = self.processor.chunk_text(snippet, chunk_size=90, chunk_overlap=0)
        selected = pieces[:3] if pieces else [self.processor.clean_text(snippet)]
        cleaned_points: List[str] = []
        for idx, piece in enumerate(selected, start=1):
            label = keywords[idx - 1] if idx - 1 < len(keywords) else f"要点{idx}"
            cleaned_points.append(f"{idx}. {label}：{piece}")
        return " ".join(cleaned_points)

    def _build_application(self, role_type: str, source_title: str, keywords: List[str]) -> str:
        hint = ROLE_APPLICATION_HINTS.get(role_type, "适合知识检索和解释场景。")
        keyword_text = "、".join(keywords[:3]) if keywords else self.processor.clean_text(source_title)[:12]
        return f"围绕{keyword_text}进行问答、检索与解释。{hint}"

    def _card_signature(self, card: Dict[str, Any]) -> Tuple[str, Tuple[str, ...], str]:
        title = self.processor.clean_text(str(card.get("title") or ""))
        keywords = tuple(sorted((card.get("keywords") or [])[:4]))
        definition = self.processor.clean_text(str(card.get("definition") or ""))[:80]
        return title, keywords, definition

    def _is_near_duplicate(self, keyword_set: Set[str], seen_keyword_sets: List[Set[str]]) -> bool:
        if not keyword_set:
            return False
        for seen in seen_keyword_sets:
            overlap = len(keyword_set & seen)
            union = len(keyword_set | seen) or 1
            if overlap / union >= 0.72:
                return True
        return False

    def _materialize_card(self, base_card: Dict[str, Any], index: int) -> Dict[str, Any]:
        title = f"{base_card['title']} [{index + 1}]"
        content = "\n".join(
            [
                f"标题：{title}",
                f"定义：{base_card['definition']}",
                f"要点：{base_card['key_points']}",
                f"应用：{base_card['application']}",
                f"来源：{base_card['source']}",
            ]
        )
        return {
            "title": title,
            "content": content,
            "source": base_card["source"],
            "role_type": base_card["role_type"],
            "keywords": list(base_card.get("keywords") or []),
        }

    def _write_entries_jsonl(self, entries_path: Path, entries: List[Dict[str, Any]]) -> None:
        entries_path.parent.mkdir(parents=True, exist_ok=True)
        with entries_path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
