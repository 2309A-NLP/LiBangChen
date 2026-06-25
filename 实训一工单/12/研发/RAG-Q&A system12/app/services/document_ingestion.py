"""Document ingestion service.

Loads PDFs, extracts content, chunks it for retrieval, and manages source files.
When PDF_PARSER_PROVIDER=doubao, each PDF page is rendered as an image and sent
to the already configured OpenAI-compatible Doubao/Ark chat completion API.
When PDF_PARSER_PROVIDER=auto, text is extracted locally first and only pages
that look image-heavy or chart-heavy are upgraded with Doubao vision parsing.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import md5
import io
import json
import logging
from pathlib import Path
import re
from threading import Lock
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings


logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A text chunk extracted from one source document."""

    chunk_id: str
    source_id: str
    page_number: int | None
    text: str


class DocumentIngestionService:
    """Load PDF documents, extract text/visual content, and build chunks."""

    CACHE_SCHEMA_VERSION = 2
    DOUBAO_PROMPT_VERSION = "v2_chart_aware"
    PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
    PAGE_STAMP_PATTERN = re.compile(r"^\d+-\d+-\d+$")
    TABLE_OF_CONTENTS_DOT_PATTERN = re.compile(r"[.\u2026]{6,}")
    TABLE_LINE_PATTERN = re.compile(
        r"(\u5355\u4f4d[:\uff1a]|\u91d1\u989d|\u5360\u6bd4|\u9879\u76ee|"
        r"\u7c7b\u578b|\u5e74\u5ea6|\u5ba2\u6237|\u9886\u57df)"
    )
    API_PAGE_MARKER_PATTERN = re.compile(
        r"<!--\s*page\s*:\s*(\d+)\s*-->|^#{1,3}\s*(?:Page|\u7b2c\s*(\d+)\s*\u9875)",
        re.IGNORECASE | re.MULTILINE,
    )
    CHART_PAGE_HINT_PATTERN = re.compile(
        r"(\u56fe\s*\d+|\u56fe\u8868|\u6d41\u7a0b\u56fe|\u7ec4\u7ec7\u67b6\u6784|\u67b6\u6784\u56fe|"
        r"\u7ed3\u6784\u56fe|\u793a\u610f\u56fe|\u8d8b\u52bf\u56fe|\u6298\u7ebf\u56fe|\u67f1\u72b6\u56fe|"
        r"\u6761\u5f62\u56fe|\u997c\u56fe|\u96f7\u8fbe\u56fe|\u6563\u70b9\u56fe|\u66f2\u7ebf\u56fe)"
    )
    DOUBAO_IMAGE_RENDER_SCALE = 1.2
    DOUBAO_IMAGE_QUALITY = 75
    DOUBAO_IMAGE_TIMEOUT_SECONDS = 45.0
    DOUBAO_CONCURRENT_WORKERS = 8
    AUTO_VISION_TEXT_THRESHOLD = 200

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._chunks: list[DocumentChunk] = []
        self._warnings: list[str] = []
        self._last_loaded_at: str | None = None
        self._source_files: list[str] = []
        self._selected_sources: set[str] = set()
        self._load_lock = Lock()
        self._cache_lock = Lock()

    def load_document(
        self,
        force: bool = False,
        source_files: list[str] | None = None,
    ) -> None:
        """Load and parse all discovered PDF documents."""
        with self._load_lock:
            if self._chunks and not force:
                return

            self._chunks = []
            self._warnings = []
            self._source_files = []
            pdf_paths = self._discover_pdf_paths(source_files=source_files)

            if not pdf_paths:
                self._warnings.append(
                    f"No PDF files found in source directory: {self.settings.source_pdf_dir}"
                )
                self._last_loaded_at = datetime.now(timezone.utc).isoformat()
                self._selected_sources = set()
                self._prune_document_cache(set())
                return

            parser_provider = self.settings.pdf_parser_provider.strip().lower()
            cache_payload = self._load_document_cache()
            cache_entries = cache_payload.get("entries", {})
            active_source_files = {path.name for path in pdf_paths}
            cache_changed = False
            if not source_files:
                cache_changed = self._prune_stale_cache_entries(cache_entries, active_source_files)

            for pdf_path in pdf_paths:
                self._source_files.append(pdf_path.name)
                entry, was_cache_hit = self._load_or_parse_entry(
                    pdf_path=pdf_path,
                    parser_provider=parser_provider,
                    cache_entries=cache_entries,
                )
                self._chunks.extend(entry["chunks"])
                self._warnings.extend(entry["warnings"])
                cache_changed = cache_changed or (not was_cache_hit)

            if cache_changed:
                self._save_document_cache(cache_entries)

            if not self._chunks:
                self._warnings.append("No extractable text was found in any discovered PDF.")

            self._selected_sources &= set(self._source_files)
            self._last_loaded_at = datetime.now(timezone.utc).isoformat()

    def _load_or_parse_entry(
        self,
        *,
        pdf_path: Path,
        parser_provider: str,
        cache_entries: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        signature = self._build_document_signature(pdf_path, parser_provider)
        cached_entry = cache_entries.get(pdf_path.name)
        if self._is_cache_hit(cached_entry, signature):
            return self._deserialize_cache_entry(cached_entry), True

        entry = self._parse_document_entry(pdf_path, parser_provider)
        cache_entries[pdf_path.name] = self._serialize_cache_entry(signature, entry)
        return entry, False

    def _parse_document_entry(self, pdf_path: Path, parser_provider: str) -> dict[str, Any]:
        if parser_provider in {"doubao", "doubao_vision", "doubao-vision", "ark", "api"}:
            return self._parse_pdf_with_doubao_vision(pdf_path)
        if parser_provider == "auto":
            return self._parse_pdf_with_auto(pdf_path)
        return self._parse_pdf_with_pypdf(pdf_path)

    def _parse_pdf_with_pypdf(self, pdf_path: Path) -> dict[str, Any]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return {
                "chunks": [],
                "warnings": ["pypdf is not installed, unable to parse PDF."],
            }

        warnings: list[str] = []
        chunks: list[DocumentChunk] = []
        pypdf_logger = logging.getLogger("pypdf")
        previous_level = pypdf_logger.level
        pypdf_logger.setLevel(logging.ERROR)

        try:
            try:
                reader = PdfReader(str(pdf_path))
            except Exception as exc:
                return {
                    "chunks": [],
                    "warnings": [f"Failed to read PDF {pdf_path.name}: {exc}"],
                }

            for page_index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                chunks.extend(self._build_chunks_from_page_text(pdf_path, page_index, text))
        finally:
            pypdf_logger.setLevel(previous_level)

        if not chunks:
            warnings.append(f"No extractable text was found in PDF: {pdf_path.name}")
        return {"chunks": chunks, "warnings": warnings}

    def _parse_pdf_with_auto(self, pdf_path: Path) -> dict[str, Any]:
        base_result = self._parse_pdf_with_pypdf(pdf_path)
        if not self._can_use_doubao_vision():
            return base_result

        page_texts = self._extract_pdf_page_texts(pdf_path)
        if not page_texts:
            return self._parse_pdf_with_doubao_vision(pdf_path)

        candidate_pages = [
            page_number
            for page_number, text in page_texts
            if self._should_upgrade_page_with_vision(text)
        ]
        if not candidate_pages:
            return base_result

        vision_pages, vision_warnings = self._call_doubao_pages_markdown(pdf_path, candidate_pages)
        if not vision_pages:
            base_result["warnings"].extend(vision_warnings)
            return base_result

        chunks: list[DocumentChunk] = []
        for page_number, page_text in page_texts:
            effective_text = vision_pages.get(page_number, page_text)
            provider_tag = "vision" if page_number in vision_pages else None
            chunks.extend(
                self._build_chunks_from_page_text(
                    pdf_path,
                    page_number,
                    effective_text,
                    provider_tag=provider_tag,
                )
            )

        warnings = list(base_result["warnings"])
        warnings.extend(vision_warnings)
        if not chunks:
            warnings.append(f"No extractable text was found in PDF: {pdf_path.name}")
        return {"chunks": chunks, "warnings": warnings}

    def _parse_pdf_with_doubao_vision(self, pdf_path: Path) -> dict[str, Any]:
        if not self._can_use_doubao_vision():
            return {
                "chunks": [],
                "warnings": [
                    f"Doubao image parser is not fully configured for PDF: {pdf_path.name}"
                ],
            }

        try:
            markdown = self._call_doubao_pdf_markdown(pdf_path)
        except Exception as exc:
            return {
                "chunks": [],
                "warnings": [f"Doubao image parser failed for PDF {pdf_path.name}: {exc}"],
            }

        page_sections = self._parse_api_page_markdown(markdown)
        if not page_sections and markdown.strip():
            page_sections = [(None, markdown)]

        chunks: list[DocumentChunk] = []
        for page_number, page_text in page_sections:
            chunks.extend(
                self._build_chunks_from_page_text(
                    pdf_path,
                    page_number,
                    page_text,
                    provider_tag="doubao",
                )
            )

        warnings: list[str] = []
        if not chunks:
            warnings.append(f"Doubao returned no extractable Markdown for PDF: {pdf_path.name}")
        return {"chunks": chunks, "warnings": warnings}

    def _extract_pdf_page_texts(self, pdf_path: Path) -> list[tuple[int, str]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return []

        pypdf_logger = logging.getLogger("pypdf")
        previous_level = pypdf_logger.level
        pypdf_logger.setLevel(logging.ERROR)
        try:
            reader = PdfReader(str(pdf_path))
            return [
                (page_index, page.extract_text() or "")
                for page_index, page in enumerate(reader.pages, start=1)
            ]
        except Exception:
            return []
        finally:
            pypdf_logger.setLevel(previous_level)

    def get_page_texts(self, pdf_name: str) -> list[tuple[int, str]]:
        """公开接口：用 pypdf 提取 PDF 每页文字（速度快，不含图表）。

        用于图表兜底时快速定位候选页面。
        """
        pdf_path = self.settings.source_pdf_dir / pdf_name
        if not pdf_path.exists():
            return []
        return self._extract_pdf_page_texts(pdf_path)

    def _build_chunks_from_page_text(
        self,
        pdf_path: Path,
        page_number: int | None,
        text: str,
        *,
        provider_tag: str | None = None,
    ) -> list[DocumentChunk]:
        chunks = self._split_page_text(text)
        built: list[DocumentChunk] = []
        page_part = f"page-{page_number}" if page_number is not None else "page-unknown"
        middle = f"-{provider_tag}" if provider_tag else ""
        for chunk_index, chunk_text in enumerate(chunks, start=1):
            built.append(
                DocumentChunk(
                    chunk_id=f"{pdf_path.stem}-{page_part}{middle}-chunk-{chunk_index}",
                    source_id=pdf_path.name,
                    page_number=page_number,
                    text=chunk_text,
                )
            )
        return built

    def _should_upgrade_page_with_vision(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        if len(normalized) < self.AUTO_VISION_TEXT_THRESHOLD:
            return True
        if self.CHART_PAGE_HINT_PATTERN.search(normalized):
            return True
        return False

    def _can_use_doubao_vision(self) -> bool:
        return bool(
            self.settings.llm_api_key
            and self.settings.llm_base_url
            and self.settings.llm_model
        )

    def parse_pages_with_vision(
        self,
        pdf_name: str,
        page_numbers: list[int],
    ) -> tuple[dict[int, str], list[str]]:
        """公开接口：使用 Doubao 多模态实时解析指定 PDF 的指定页面。

        用于图表兜底——当关键词检索无法命中图表内容时，
        由 RetrievalGenerationService 直接调用此接口对候选页面截图并解析。

        Returns:
            (page_number -> markdown_text, warnings)
        """
        if not self._can_use_doubao_vision():
            return {}, ["Doubao multi-modal is not configured."]
        pdf_path = self.settings.source_pdf_dir / pdf_name
        if not pdf_path.exists():
            return {}, [f"PDF not found: {pdf_name}"]
        return self._call_doubao_pages_markdown(pdf_path, page_numbers)

    def _call_doubao_pdf_markdown(self, pdf_path: Path) -> str:
        """并发调用 Doubao 解析整份 PDF，大幅加速全量解析。"""
        pending = list(self._iter_pdf_pages_as_jpeg_base64(pdf_path))
        if not pending:
            return ""

        logger.info(
            "Doubao vision: processing full PDF %s (%d pages) with %d concurrent workers",
            pdf_path.name,
            len(pending),
            self.DOUBAO_CONCURRENT_WORKERS,
        )

        results: dict[int, str] = {}
        fatal = False

        with ThreadPoolExecutor(max_workers=self.DOUBAO_CONCURRENT_WORKERS) as executor:
            future_map = {
                executor.submit(
                    self._call_doubao_page_markdown,
                    pdf_path.name,
                    page_number,
                    image_base64,
                ): page_number
                for page_number, image_base64 in pending
            }

            for future in as_completed(future_map):
                page_number = future_map[future]
                if fatal:
                    future.cancel()
                    continue
                try:
                    markdown = future.result()
                    if markdown.strip():
                        results[page_number] = markdown
                except Exception as exc:
                    logger.warning(
                        "Doubao image parser failed for %s page %d: %s",
                        pdf_path.name, page_number, exc,
                    )
                    if self._is_non_retriable_doubao_error(exc):
                        fatal = True

        return "\n\n".join(
            results[page_number]
            for page_number in sorted(results)
        )

    def _call_doubao_pages_markdown(
        self,
        pdf_path: Path,
        page_numbers: list[int],
    ) -> tuple[dict[int, str], list[str]]:
        page_set = set(page_numbers)
        if not page_set:
            return {}, []

        # 先渲染所有页面（CPU密集，快速），再并发调用 API（IO密集，慢）
        pending_pages = list(self._iter_pdf_pages_as_jpeg_base64(pdf_path, page_set))
        if not pending_pages:
            return {}, []

        logger.info(
            "Doubao vision: processing %d pages of %s with %d concurrent workers",
            len(pending_pages),
            pdf_path.name,
            self.DOUBAO_CONCURRENT_WORKERS,
        )

        results: dict[int, str] = {}
        warnings: list[str] = []
        fatal = False

        with ThreadPoolExecutor(max_workers=self.DOUBAO_CONCURRENT_WORKERS) as executor:
            future_map = {
                executor.submit(
                    self._call_doubao_page_markdown,
                    pdf_path.name,
                    page_number,
                    image_base64,
                ): page_number
                for page_number, image_base64 in pending_pages
            }

            for future in as_completed(future_map):
                page_number = future_map[future]
                if fatal:
                    future.cancel()
                    continue
                try:
                    markdown = future.result()
                except Exception as exc:
                    warnings.append(
                        f"Doubao image parser failed for PDF {pdf_path.name}, page {page_number}: {exc}"
                    )
                    if self._is_non_retriable_doubao_error(exc):
                        warnings.append(
                            "Doubao image parser is unavailable for this run; "
                            "cancelling remaining pages."
                        )
                        fatal = True
                    continue

                sections = self._parse_api_page_markdown(markdown)
                if sections:
                    exact_match = next(
                        (text for number, text in sections if number == page_number), None
                    )
                    if exact_match:
                        results[page_number] = exact_match
                        continue
                if markdown.strip():
                    results[page_number] = markdown

        return results, warnings

    def _is_non_retriable_doubao_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "http 401" in message
            or "http 403" in message
            or "accountoverdue" in message
            or "account overdue" in message
        )

    def _iter_pdf_pages_as_jpeg_base64(
        self,
        pdf_path: Path,
        only_pages: set[int] | None = None,
    ) -> Iterator[tuple[int, str]]:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RuntimeError("pypdfium2 is required to render PDF pages for Doubao image parsing.") from exc

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            for page_index in range(len(pdf)):
                page_number = page_index + 1
                if only_pages is not None and page_number not in only_pages:
                    continue
                page = pdf[page_index]
                bitmap = page.render(scale=self.DOUBAO_IMAGE_RENDER_SCALE)
                image = bitmap.to_pil()
                try:
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=self.DOUBAO_IMAGE_QUALITY, optimize=True)
                    yield page_number, base64.b64encode(buffer.getvalue()).decode("ascii")
                finally:
                    image.close()
                    close_bitmap = getattr(bitmap, "close", None)
                    if callable(close_bitmap):
                        close_bitmap()
                    close_page = getattr(page, "close", None)
                    if callable(close_page):
                        close_page()
        finally:
            close_pdf = getattr(pdf, "close", None)
            if callable(close_pdf):
                close_pdf()

    def _call_doubao_page_markdown(self, file_name: str, page_number: int, image_base64: str) -> str:
        assert self.settings.llm_api_key
        assert self.settings.llm_base_url
        assert self.settings.llm_model

        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_doubao_page_prompt(file_name, page_number)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        },
                    ],
                }
            ],
        }
        request = Request(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        timeout = max(float(self.settings.llm_timeout_seconds), self.DOUBAO_IMAGE_TIMEOUT_SECONDS)
        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Doubao image parser HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Doubao image parser connection failed: {exc.reason}") from exc

        return self._extract_chat_completion_text(data)

    def _build_doubao_page_prompt(self, file_name: str, page_number: int) -> str:
        return (
            f"Read this PDF page image from file {file_name}, page {page_number}. "
            "Output Chinese Markdown suitable for RAG retrieval. "
            f"Start exactly with <!-- page: {page_number} -->. "
            "Keep all visible text, headings, captions, footnotes, and table data. "
            "Convert tables to Markdown tables when possible. "
            "CRITICAL for data charts (bar charts, line charts, pie charts, growth charts, "
            "comparison charts): You MUST extract ALL visible numeric values — every bar height, "
            "every data point, every percentage label, every growth rate including negative ones. "
            "List each category with its exact value in a table or bullet list. "
            "For charts showing growth rates, list every sector/industry with its growth rate "
            "value and explicitly state which is the highest (fastest growth) and which is "
            "negative (decline). "
            "For organization charts: list every department, sub-department, and reporting line. "
            "Do not summarize or skip any data point. "
            "Do not wrap the answer in code fences. Do not add unrelated commentary."
        )

    def _extract_chat_completion_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Doubao image parser response is missing choices.")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("Doubao image parser response choice is invalid.")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Doubao image parser response is missing message.")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text_blocks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            joined = "".join(text_blocks).strip()
            if joined:
                return joined
        raise RuntimeError("Doubao image parser response did not contain text output.")

    def _parse_api_page_markdown(self, markdown: str) -> list[tuple[int | None, str]]:
        matches = list(self.API_PAGE_MARKER_PATTERN.finditer(markdown))
        if not matches:
            return []

        sections: list[tuple[int | None, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            page_number_text = match.group(1) or match.group(2)
            page_number = int(page_number_text) if page_number_text else None
            page_text = markdown[start:end].strip()
            if page_text:
                sections.append((page_number, page_text))
        return sections

    def _discover_pdf_paths(self, source_files: list[str] | None = None) -> list[Path]:
        """Discover PDFs in source directory, falling back to SOURCE_PDF_PATH."""
        source_dir = self.settings.source_pdf_dir
        if source_files:
            paths = []
            for item in source_files:
                safe_name = Path(item).name
                target = source_dir / safe_name
                if target.exists() and target.suffix.lower() == ".pdf":
                    paths.append(target)
            return sorted(paths)
        discovered = sorted(source_dir.glob("*.pdf"))
        if discovered:
            return discovered
        if self.settings.source_pdf_path.exists():
            return [self.settings.source_pdf_path]
        return []

    def get_pdf_paths(self, source_files: list[str] | None = None) -> list[Path]:
        """Resolve source file names to absolute Path objects in the PDF directory."""
        source_dir = self.settings.source_pdf_dir
        paths: list[Path] = []
        resolved: set[str] = set()
        for item in (source_files or []):
            safe_name = Path(item).name
            target = source_dir / safe_name
            if target.exists() and target.suffix.lower() == ".pdf":
                key = str(target.resolve())
                if key not in resolved:
                    paths.append(target)
                    resolved.add(key)
        return paths

    def _split_page_text(self, text: str) -> list[str]:
        """Split a page into chunks."""
        normalized = self._normalize_text(text)
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
        """Keep table-like lines together as much as possible."""
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

    def _normalize_text(self, text: str) -> str:
        """Clean text extracted from PDFs or API Markdown."""
        text = text.replace("\u3000", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        cleaned_lines: list[str] = []
        for line in lines:
            if not line:
                continue
            if self.PAGE_STAMP_PATTERN.fullmatch(line):
                continue
            if self._looks_like_document_header(line):
                continue
            if self._looks_like_table_of_contents_line(line):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def _extract_paragraphs(self, text: str) -> list[str]:
        """Extract paragraphs, falling back to sentence boundaries."""
        if "\n" in text:
            paragraphs = [
                item.strip() for item in self.PARAGRAPH_SPLIT_PATTERN.split(text) if item.strip()
            ]
            if paragraphs:
                return paragraphs
        return [
            item.strip()
            for item in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b;!?])\s+", text)
            if item.strip()
        ]

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        """Split oversized paragraphs on sentence boundaries."""
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b;!?])", paragraph)
            if item.strip()
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
        """Hard split text by max_chunk_length."""
        max_len = self.settings.max_chunk_length
        return [text[index : index + max_len].strip() for index in range(0, len(text), max_len)]

    def _looks_like_document_header(self, line: str) -> bool:
        return "\u62db\u80a1\u8bf4\u660e\u4e66" in line and len(line) <= 40

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
        """Return currently selected chunks."""
        if not self._selected_sources:
            return list(self._chunks)
        return [chunk for chunk in self._chunks if chunk.source_id in self._selected_sources]

    def all_chunks(self) -> list[DocumentChunk]:
        """Return all chunks, ignoring source selection."""
        return list(self._chunks)

    def available_source_files(self) -> list[str]:
        """Return discovered source file names."""
        return list(self._source_files)

    def select_sources(self, source_files: list[str] | None) -> None:
        """Set the source subset used for retrieval. None or empty means all."""
        if not source_files:
            self._selected_sources = set()
            return
        self._selected_sources = {Path(item).name for item in source_files if str(item).strip()}

    def save_uploaded_pdf(self, file_name: str, content: bytes) -> str:
        """Save an uploaded PDF into the source directory."""
        target_dir = self.settings.source_pdf_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name or "uploaded.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{safe_name}.pdf"
        target_path = target_dir / safe_name
        target_path.write_bytes(content)
        return safe_name

    def delete_source(self, source_id: str) -> bool:
        """Delete a source file. Returns True if found."""
        known_sources = set(self._source_files) | {path.name for path in self._discover_pdf_paths()}
        if source_id not in known_sources:
            return False
        source_path = self.settings.source_pdf_dir / source_id
        if source_path.exists():
            source_path.unlink()
        self._selected_sources.discard(source_id)
        self._prune_document_cache({path.name for path in self._discover_pdf_paths()})
        return True

    def list_documents(self) -> list[dict]:
        """Return document-level summaries."""
        doc_map: dict[str, list[DocumentChunk]] = {}
        for chunk in self._chunks:
            doc_map.setdefault(chunk.source_id, []).append(chunk)

        result = []
        for source_id in self._source_files:
            chunks = doc_map.get(source_id, [])
            pages = [chunk.page_number for chunk in chunks if chunk.page_number is not None]
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
        """Return all chunks for a specific source file."""
        if source_id not in set(self._source_files):
            raise FileNotFoundError(source_id)
        return [
            {
                "chunk_id": chunk.chunk_id,
                "page_number": chunk.page_number,
                "text": chunk.text,
                "char_count": len(chunk.text),
            }
            for chunk in self._chunks
            if chunk.source_id == source_id
        ]

    def status(self) -> dict[str, object]:
        """Return ingestion status."""
        return {
            "source_pdf_dir": str(self.settings.source_pdf_dir),
            "source_files": list(self._source_files),
            "selected_sources": sorted(self._selected_sources),
            "document_count": len(self._source_files),
            "document_loaded": bool(self._chunks),
            "chunk_count": len(self._chunks),
            "selected_chunk_count": len(self.chunks()),
            "last_loaded_at": self._last_loaded_at,
            "warnings": list(self._warnings),
        }

    def _build_document_signature(self, pdf_path: Path, parser_provider: str) -> str:
        stat = pdf_path.stat()
        digest = md5()
        for part in (
            pdf_path.name,
            str(stat.st_size),
            str(stat.st_mtime_ns),
            parser_provider,
            str(self.settings.max_chunk_length),
            str(self.settings.table_chunk_length),
            self.DOUBAO_PROMPT_VERSION,
            self.settings.llm_model or "",
        ):
            digest.update(part.encode("utf-8"))
        return digest.hexdigest()

    def _load_document_cache(self) -> dict[str, Any]:
        cache_path = self.settings.document_cache_path
        if not cache_path.exists():
            return {"version": self.CACHE_SCHEMA_VERSION, "entries": {}}
        with self._cache_lock:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"version": self.CACHE_SCHEMA_VERSION, "entries": {}}
        if not isinstance(payload, dict):
            return {"version": self.CACHE_SCHEMA_VERSION, "entries": {}}
        if payload.get("version") != self.CACHE_SCHEMA_VERSION:
            return {"version": self.CACHE_SCHEMA_VERSION, "entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return {"version": self.CACHE_SCHEMA_VERSION, "entries": {}}
        return {"version": self.CACHE_SCHEMA_VERSION, "entries": entries}

    def _save_document_cache(self, entries: dict[str, Any]) -> None:
        cache_path = self.settings.document_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.CACHE_SCHEMA_VERSION, "entries": entries}
        with self._cache_lock:
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _serialize_cache_entry(self, signature: str, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "signature": signature,
            "warnings": list(entry["warnings"]),
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "page_number": chunk.page_number,
                    "text": chunk.text,
                }
                for chunk in entry["chunks"]
            ],
        }

    def _deserialize_cache_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        raw_chunks = entry.get("chunks", [])
        chunks = [
            DocumentChunk(
                chunk_id=str(item.get("chunk_id")),
                source_id=str(item.get("source_id")),
                page_number=item.get("page_number"),
                text=str(item.get("text", "")),
            )
            for item in raw_chunks
            if isinstance(item, dict)
        ]
        warnings = [str(item) for item in entry.get("warnings", []) if str(item).strip()]
        return {"chunks": chunks, "warnings": warnings}

    def _is_cache_hit(self, entry: Any, signature: str) -> bool:
        return isinstance(entry, dict) and entry.get("signature") == signature

    def _prune_stale_cache_entries(
        self,
        cache_entries: dict[str, Any],
        active_source_files: set[str],
    ) -> bool:
        stale_keys = [key for key in cache_entries.keys() if key not in active_source_files]
        for key in stale_keys:
            cache_entries.pop(key, None)
        return bool(stale_keys)

    def _prune_document_cache(self, active_source_files: set[str]) -> None:
        payload = self._load_document_cache()
        entries = payload.get("entries", {})
        if not isinstance(entries, dict):
            return
        if self._prune_stale_cache_entries(entries, active_source_files):
            self._save_document_cache(entries)
