from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
from pathlib import Path
import re

from app.core.config import Settings
from app.services.ocr import OCRService


@dataclass
class DocumentChunk:
    chunk_id: str
    source_id: str
    page_number: int | None
    text: str


class DocumentIngestionService:
    PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
    PAGE_STAMP_PATTERN = re.compile(r"^\d+-\d+-\d+$")
    TABLE_OF_CONTENTS_DOT_PATTERN = re.compile(r"[.\u2026]{6,}")
    TABLE_LINE_PATTERN = re.compile(r"(单位[:：]?|金额|占比|项目|类型|年度|客户|领域)")
    DIGIT_PATTERN = re.compile(r"\d+")
    HEADER_FOOTER_WINDOW_LINES = 3
    HEADER_FOOTER_MIN_REPEAT_PAGES = 3
    HEADER_FOOTER_MIN_REPEAT_RATIO = 0.6

    def __init__(self, settings: Settings, ocr_service: OCRService | None = None) -> None:
        self.settings = settings
        self.ocr_service = ocr_service or OCRService(
            enabled=settings.ocr_enabled,
            language=settings.ocr_language,
        )
        self._chunks: list[DocumentChunk] = []
        self._warnings: list[str] = []
        self._last_loaded_at: str | None = None
        self._source_files: list[str] = []
        self._selected_sources: set[str] = set()

    def load_document(self, force: bool = False) -> None:
        if self._chunks and not force:
            return

        self._chunks = []
        self._warnings = []
        self._source_files = []
        pdf_paths = self._discover_pdf_paths()

        if not pdf_paths:
            self._warnings.append(
                f"No PDF files found in source directory: {self.settings.source_pdf_dir}"
            )
            self._last_loaded_at = datetime.now(timezone.utc).isoformat()
            return

        self._ingest_pdf_paths(pdf_paths)

    def load_single_document(self, source_id: str) -> None:
        pdf_path = self.settings.source_pdf_dir / source_id
        if not pdf_path.exists():
            raise FileNotFoundError(source_id)

        self._chunks = [chunk for chunk in self._chunks if chunk.source_id != source_id]
        self._warnings = [
            warning for warning in self._warnings if source_id not in warning
        ]
        if source_id not in self._source_files:
            self._source_files.append(source_id)
            self._source_files.sort()

        self._ingest_pdf_paths([pdf_path], reset_source_files=False)

    def _ingest_pdf_paths(
        self,
        pdf_paths: list[Path],
        reset_source_files: bool = True,
    ) -> None:
        try:
            from pypdf import PdfReader
        except ImportError:
            self._warnings.append("pypdf is not installed, unable to parse PDF.")
            self._last_loaded_at = datetime.now(timezone.utc).isoformat()
            return

        pypdf_logger = logging.getLogger("pypdf")
        previous_level = pypdf_logger.level
        pypdf_logger.setLevel(logging.ERROR)

        try:
            if reset_source_files:
                self._source_files = []

            for pdf_path in pdf_paths:
                if pdf_path.name not in self._source_files:
                    self._source_files.append(pdf_path.name)
                try:
                    reader = PdfReader(str(pdf_path))
                except Exception as exc:
                    self._warnings.append(f"Failed to read PDF {pdf_path.name}: {exc}")
                    continue

                page_texts = [page.extract_text() or "" for page in reader.pages]
                page_texts = self._maybe_apply_ocr(pdf_path, page_texts)
                repeated_margin_signatures = self._detect_repeated_margin_signatures(page_texts)

                document_chunk_count = 0
                for page_index, text in enumerate(page_texts, start=1):
                    chunks = self._split_page_text(text, repeated_margin_signatures)
                    for chunk_index, chunk_text in enumerate(chunks, start=1):
                        document_chunk_count += 1
                        self._chunks.append(
                            DocumentChunk(
                                chunk_id=f"{pdf_path.stem}-page-{page_index}-chunk-{chunk_index}",
                                source_id=pdf_path.name,
                                page_number=page_index,
                                text=chunk_text,
                            )
                        )

                if document_chunk_count == 0:
                    self._warnings.append(
                        f"No extractable text was found in PDF: {pdf_path.name}"
                    )
        finally:
            pypdf_logger.setLevel(previous_level)

        if not self._chunks:
            self._warnings.append("No extractable text was found in any discovered PDF.")

        self._source_files = sorted(set(self._source_files))
        self._selected_sources &= set(self._source_files)
        self._last_loaded_at = datetime.now(timezone.utc).isoformat()

    def _maybe_apply_ocr(self, pdf_path: Path, page_texts: list[str]) -> list[str]:
        if not page_texts:
            return page_texts
        if not self._should_try_ocr(page_texts):
            return page_texts
        if not self.ocr_service.is_available():
            self._warnings.append(
                f"PDF may be scanned, but OCR is unavailable for {pdf_path.name}."
            )
            return page_texts

        ocr_texts = self.ocr_service.extract_page_texts(pdf_path)
        if not ocr_texts:
            self._warnings.append(f"OCR did not extract usable text from {pdf_path.name}.")
            return page_texts

        merged: list[str] = []
        for original, ocr_text in zip(page_texts, ocr_texts, strict=False):
            merged.append(ocr_text if len(ocr_text.strip()) > len(original.strip()) else original)

        if len(ocr_texts) > len(merged):
            merged.extend(ocr_texts[len(merged):])

        self._warnings.append(f"OCR was applied to scanned PDF: {pdf_path.name}")
        return merged

    def _should_try_ocr(self, page_texts: list[str]) -> bool:
        if not page_texts:
            return False

        short_pages = 0
        empty_pages = 0
        for text in page_texts:
            cleaned = text.strip()
            if not cleaned:
                empty_pages += 1
                continue
            if len(cleaned) < 20:
                short_pages += 1

        total = len(page_texts)
        return empty_pages == total or (empty_pages + short_pages) / total >= 0.6

    def _discover_pdf_paths(self) -> list[Path]:
        source_dir = self.settings.source_pdf_dir
        discovered = sorted(source_dir.glob("*.pdf"))
        if discovered:
            return discovered
        if self.settings.source_pdf_path.exists():
            return [self.settings.source_pdf_path]
        return []

    def _split_page_text(
        self,
        text: str,
        repeated_margin_signatures: set[str] | None = None,
    ) -> list[str]:
        normalized = self._normalize_text(text, repeated_margin_signatures or set())
        if not normalized:
            return []

        if self._looks_like_table_page(normalized):
            return self._split_table_page_text(normalized)

        paragraphs = self._extract_paragraphs(normalized)
        chunks: list[str] = []
        current = ""
        max_len = self.settings.max_chunk_length

        for paragraph in paragraphs:
            if len(paragraph) > max_len:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._split_oversized_paragraph(paragraph))
                continue

            candidate = f"{current}\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= max_len:
                current = candidate
            else:
                if current:
                    chunks.append(current.strip())
                current = paragraph

        if current:
            chunks.append(current.strip())

        return [chunk for chunk in chunks if chunk]

    def _split_table_page_text(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        max_len = self.settings.table_chunk_length
        chunks: list[str] = []
        current_lines: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current_lines and current_len + line_len > max_len:
                chunks.append("\n".join(current_lines).strip())
                current_lines = []
                current_len = 0
            current_lines.append(line)
            current_len += line_len

        if current_lines:
            chunks.append("\n".join(current_lines).strip())

        return [chunk for chunk in chunks if chunk]

    def _normalize_text(self, text: str, repeated_margin_signatures: set[str]) -> str:
        text = text.replace("\u3000", " ")
        lines = [self._normalize_line(line) for line in text.splitlines()]
        cleaned_lines: list[str] = []
        last_index = len(lines) - 1

        for index, line in enumerate(lines):
            if not line:
                continue
            if self.PAGE_STAMP_PATTERN.fullmatch(line):
                continue
            if self._is_repeated_margin_line(
                line=line,
                line_index=index,
                last_index=last_index,
                repeated_margin_signatures=repeated_margin_signatures,
            ):
                continue
            if self._looks_like_document_header(line):
                continue
            if self._looks_like_table_of_contents_line(line):
                continue
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def _normalize_line(self, line: str) -> str:
        return re.sub(r"\s+", " ", line).strip()

    def _detect_repeated_margin_signatures(self, page_texts: list[str]) -> set[str]:
        if len(page_texts) < self.HEADER_FOOTER_MIN_REPEAT_PAGES:
            return set()

        signature_counts: dict[str, int] = {}
        threshold = max(
            self.HEADER_FOOTER_MIN_REPEAT_PAGES,
            math.ceil(len(page_texts) * self.HEADER_FOOTER_MIN_REPEAT_RATIO),
        )

        for page_text in page_texts:
            margin_signatures = {
                self._line_signature(line)
                for line in self._candidate_margin_lines(page_text)
                if self._is_header_footer_candidate(line)
            }
            for signature in margin_signatures:
                signature_counts[signature] = signature_counts.get(signature, 0) + 1

        return {
            signature
            for signature, count in signature_counts.items()
            if count >= threshold
        }

    def _candidate_margin_lines(self, text: str) -> list[str]:
        lines = [
            self._normalize_line(line)
            for line in text.replace("\u3000", " ").splitlines()
            if self._normalize_line(line)
        ]
        if not lines:
            return []

        window = min(self.HEADER_FOOTER_WINDOW_LINES, len(lines))
        return lines[:window] + lines[-window:]

    def _line_signature(self, line: str) -> str:
        normalized = self.DIGIT_PATTERN.sub("#", line.lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_header_footer_candidate(self, line: str) -> bool:
        if self.PAGE_STAMP_PATTERN.fullmatch(line):
            return True
        if len(line) < 2 or len(line) > 120:
            return False
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", line))

    def _is_repeated_margin_line(
        self,
        line: str,
        line_index: int,
        last_index: int,
        repeated_margin_signatures: set[str],
    ) -> bool:
        if not repeated_margin_signatures:
            return False

        window = self.HEADER_FOOTER_WINDOW_LINES
        in_header = line_index < window
        in_footer = line_index > last_index - window
        if not in_header and not in_footer:
            return False

        return self._line_signature(line) in repeated_margin_signatures

    def _extract_paragraphs(self, text: str) -> list[str]:
        if "\n" in text:
            paragraphs = [
                item.strip() for item in self.PARAGRAPH_SPLIT_PATTERN.split(text) if item.strip()
            ]
            if paragraphs:
                return paragraphs
        return [item.strip() for item in re.split(r"(?<=[。！？；;!?])\s+", text) if item.strip()]

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        sentences = [
            item.strip() for item in re.split(r"(?<=[。！？；;!?])", paragraph) if item.strip()
        ]
        if not sentences:
            return [paragraph[: self.settings.max_chunk_length]]

        chunks: list[str] = []
        current = ""
        max_len = self.settings.max_chunk_length
        for sentence in sentences:
            if len(sentence) > max_len:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._hard_split(sentence))
                continue

            candidate = f"{current}{sentence}".strip() if current else sentence
            if len(candidate) <= max_len:
                current = candidate
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())
        return chunks

    def _hard_split(self, text: str) -> list[str]:
        max_len = self.settings.max_chunk_length
        return [text[index : index + max_len].strip() for index in range(0, len(text), max_len)]

    def _looks_like_document_header(self, line: str) -> bool:
        lowered = line.lower()
        return ("招股说明书" in line or "prospectus" in lowered) and len(line) <= 40

    def _looks_like_table_of_contents_line(self, line: str) -> bool:
        if self.TABLE_OF_CONTENTS_DOT_PATTERN.search(line):
            return True
        if len(line) <= 28 and re.search(r"\.{3,}\s*\d+$", line):
            return True
        return False

    def _looks_like_table_page(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 4:
            return False

        numeric_lines = sum(1 for line in lines if re.search(r"[0-9][0-9,]*\.\d{2}", line))
        header_lines = sum(1 for line in lines if self.TABLE_LINE_PATTERN.search(line))
        short_lines = sum(1 for line in lines if len(line) <= 40)

        return numeric_lines >= 3 and (header_lines >= 2 or short_lines >= 6)

    def chunks(self) -> list[DocumentChunk]:
        if not self._selected_sources:
            return list(self._chunks)
        return [chunk for chunk in self._chunks if chunk.source_id in self._selected_sources]

    def all_chunks(self) -> list[DocumentChunk]:
        return list(self._chunks)

    def available_source_files(self) -> list[str]:
        return list(self._source_files)

    def select_sources(self, source_files: list[str] | None) -> None:
        if not source_files:
            self._selected_sources = set()
            return
        available = set(self._source_files)
        self._selected_sources = {item for item in source_files if item in available}

    def save_uploaded_pdf(self, file_name: str, content: bytes) -> str:
        target_dir = self.settings.source_pdf_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name or "uploaded.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{safe_name}.pdf"
        target_path = target_dir / safe_name
        target_path.write_bytes(content)
        return safe_name

    def delete_source(self, source_id: str) -> bool:
        if source_id not in set(self._source_files):
            return False
        source_path = self.settings.source_pdf_dir / source_id
        if source_path.exists():
            source_path.unlink()
        self._chunks = [chunk for chunk in self._chunks if chunk.source_id != source_id]
        self._source_files = [item for item in self._source_files if item != source_id]
        self._selected_sources.discard(source_id)
        self._last_loaded_at = datetime.now(timezone.utc).isoformat()
        return True

    def list_documents(self) -> list[dict]:
        doc_map: dict[str, list[DocumentChunk]] = {}
        for chunk in self._chunks:
            doc_map.setdefault(chunk.source_id, []).append(chunk)

        result = []
        for source_id in self._source_files:
            chunks = doc_map.get(source_id, [])
            pages = [c.page_number for c in chunks if c.page_number is not None]
            page_range = f"{min(pages)}-{max(pages)}" if pages else "N/A"
            preview = chunks[0].text[:200] if chunks else ""
            result.append(
                {
                    "source_id": source_id,
                    "chunk_count": len(chunks),
                    "page_range": page_range,
                    "text_preview": preview,
                }
            )
        return result

    def get_document_chunks(self, source_id: str) -> list[dict]:
        if source_id not in set(self._source_files):
            raise FileNotFoundError(source_id)
        return [
            {
                "chunk_id": c.chunk_id,
                "page_number": c.page_number,
                "text": c.text,
                "char_count": len(c.text),
            }
            for c in self._chunks
            if c.source_id == source_id
        ]

    def status(self) -> dict[str, object]:
        ocr_status = self.ocr_service.status()
        return {
            "source_pdf_dir": str(self.settings.source_pdf_dir),
            "source_files": list(self._source_files),
            "selected_sources": sorted(self._selected_sources),
            "document_count": len(self._source_files),
            "document_loaded": bool(self._chunks),
            "chunk_count": len(self._chunks),
            "last_loaded_at": self._last_loaded_at,
            "warnings": list(self._warnings),
            "ocr_enabled": ocr_status.enabled,
            "ocr_available": ocr_status.available,
        }
