"""文档摄入服务模块。

负责从 PDF 文件中提取文本、分块（chunking）、以及管理知识库文档的增删查。
支持普通文本页和表格页的差异化分块策略。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any

from app.core.config import Settings


@dataclass
class DocumentChunk:
    """表示从文档中切分出的一个文本块。"""
    chunk_id: str
    source_id: str
    page_number: int | None
    text: str


class DocumentIngestionService:
    """文档摄入服务，负责 PDF 发现、文本提取、文本分块和文档管理。"""
    PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
    PAGE_STAMP_PATTERN = re.compile(r"^\d+-\d+-\d+$")
    TABLE_OF_CONTENTS_DOT_PATTERN = re.compile(r"[.…·]{6,}")
    TABLE_LINE_PATTERN = re.compile(r"(单位[:：]|金额|占比|项目|类型|年度|客户|领域)")

    def __init__(self, settings: Settings) -> None:
        """初始化摄入服务，传入全局配置。"""
        self.settings = settings
        self._chunks: list[DocumentChunk] = []
        self._warnings: list[str] = []
        self._last_loaded_at: str | None = None
        self._source_files: list[str] = []
        self._selected_sources: set[str] = set()

    def load_document(self, force: bool = False) -> None:
        """加载并解析所有 PDF 文档。force=True 时强制重新加载。"""
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

        try:
            from pypdf import PdfReader
        except ImportError:
            self._warnings.append("pypdf is not installed, unable to parse PDF.")
            self._last_loaded_at = datetime.now(timezone.utc).isoformat()
            return

        fitz_module = self._load_fitz_module()

        pypdf_logger = logging.getLogger("pypdf")
        previous_level = pypdf_logger.level
        pypdf_logger.setLevel(logging.ERROR)

        try:
            for pdf_path in pdf_paths:
                self._source_files.append(pdf_path.name)
                try:
                    reader = PdfReader(str(pdf_path))
                except Exception as exc:
                    self._warnings.append(f"Failed to read PDF {pdf_path.name}: {exc}")
                    continue

                fitz_document = self._open_fitz_document(fitz_module, pdf_path)

                document_chunk_count = 0
                for page_index, page in enumerate(reader.pages, start=1):
                    layout_page = None
                    if fitz_document is not None:
                        try:
                            layout_page = fitz_document.load_page(page_index - 1)
                        except Exception:
                            layout_page = None
                    text = self._extract_page_text(page, layout_page)
                    chunks = self._split_page_text(text)
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
                if fitz_document is not None:
                    try:
                        fitz_document.close()
                    except Exception:
                        pass
        finally:
            pypdf_logger.setLevel(previous_level)

        if not self._chunks:
            self._warnings.append("No extractable text was found in any discovered PDF.")

        self._selected_sources &= set(self._source_files)
        self._last_loaded_at = datetime.now(timezone.utc).isoformat()

    def _discover_pdf_paths(self) -> list[Path]:
        """发现源目录下的 PDF 文件，优先扫描目录，回退到单文件配置。"""
        source_dir = self.settings.source_pdf_dir
        discovered = sorted(source_dir.glob("*.pdf"))
        if discovered:
            return discovered
        if self.settings.source_pdf_path.exists():
            return [self.settings.source_pdf_path]
        return []

    def _extract_page_text(self, page: Any, layout_page: Any | None = None) -> str:
        """合并线性文本与版面文本，提升图表/结构图页面的可检索性。"""
        primary_text = page.extract_text() or ""
        layout_text = self._extract_layout_text(layout_page)
        return self._merge_page_text(primary_text, layout_text)

    def _extract_layout_text(self, layout_page: Any | None) -> str:
        """读取版面文本块，保留图表中的文本框内容。"""
        if layout_page is None:
            return ""
        try:
            blocks = layout_page.get_text("blocks")
        except Exception:
            return ""

        pieces: list[str] = []
        for block in blocks:
            if len(block) < 5:
                continue
            text = str(block[4]).strip()
            if not text:
                continue
            pieces.append(text)
        return "\n".join(pieces)

    def _merge_page_text(self, primary_text: str, layout_text: str) -> str:
        """将不同提取器的结果去重合并。"""
        primary_text = primary_text or ""
        layout_text = layout_text or ""
        if not primary_text:
            return layout_text
        if not layout_text:
            return primary_text

        normalized_primary = re.sub(r"\s+", "", primary_text)
        normalized_layout = re.sub(r"\s+", "", layout_text)
        if not normalized_layout or normalized_layout in normalized_primary:
            return primary_text
        if normalized_primary and normalized_primary in normalized_layout:
            return layout_text
        return f"{primary_text}\n{layout_text}"

    def _load_fitz_module(self):
        try:
            import fitz
        except ImportError:
            return None
        return fitz

    def _open_fitz_document(self, fitz_module: Any | None, pdf_path: Path):
        if fitz_module is None:
            return None
        try:
            return fitz_module.open(str(pdf_path))
        except Exception:
            return None

    def _split_page_text(self, text: str) -> list[str]:
        """将单页文本拆分为多个 chunk，表格页走专用策略。"""
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
        """按行拼接方式对表格页文本进行分块。"""
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
        """文本清洗：去除全角空格、页码戳、文档标题行和目录行。"""
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
        """提取段落：优先按空行分割，回退到按句末标点分割。"""
        if "\n" in text:
            paragraphs = [
                item.strip() for item in self.PARAGRAPH_SPLIT_PATTERN.split(text) if item.strip()
            ]
            if paragraphs:
                return paragraphs
        return [item.strip() for item in re.split(r"(?<=[。！？；;!?])\s+", text) if item.strip()]

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        """对超长段落按句子边界进行二次拆分。"""
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
        """硬切分：按固定长度截断，作为最后手段。"""
        max_len = self.settings.max_chunk_length
        return [text[index : index + max_len].strip() for index in range(0, len(text), max_len)]

    def _looks_like_document_header(self, line: str) -> bool:
        """判断是否为招股说明书标题行。"""
        return "招股说明书" in line and len(line) <= 40

    def _looks_like_table_of_contents_line(self, line: str) -> bool:
        """判断是否为目录行（含省略号或连续点号+页码）。"""
        if self.TABLE_OF_CONTENTS_DOT_PATTERN.search(line):
            return True
        if len(line) <= 28 and re.search(r"\.{3,}\s*\d+$", line):
            return True
        return False

    def _looks_like_table_page(self, text: str) -> bool:
        """启发式判断页面是否为表格页：检查数字行、表头关键词和短行比例。"""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 4:
            return False

        numeric_lines = sum(1 for line in lines if re.search(r"[0-9][0-9,]*\.\d{2}", line))
        header_lines = sum(1 for line in lines if self.TABLE_LINE_PATTERN.search(line))
        short_lines = sum(1 for line in lines if len(line) <= 40)

        return numeric_lines >= 3 and (header_lines >= 2 or short_lines >= 6)

    def chunks(self) -> list[DocumentChunk]:
        """返回当前选中文档的 chunk 列表（受 source 筛选影响）。"""
        if not self._selected_sources:
            return list(self._chunks)
        return [chunk for chunk in self._chunks if chunk.source_id in self._selected_sources]

    def all_chunks(self) -> list[DocumentChunk]:
        """返回所有 chunk，忽略 source 筛选。"""
        return list(self._chunks)

    def available_source_files(self) -> list[str]:
        """返回已发现的源文件名列表。"""
        return list(self._source_files)

    def select_sources(self, source_files: list[str] | None) -> None:
        """设置要检索的文档源子集。None 或空列表表示全选。"""
        if not source_files:
            self._selected_sources = set()
            return
        available = set(self._source_files)
        self._selected_sources = {item for item in source_files if item in available}

    def save_uploaded_pdf(self, file_name: str, content: bytes) -> str:
        """保存用户上传的 PDF 文件到源目录，返回安全文件名。"""
        target_dir = self.settings.source_pdf_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name or "uploaded.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{safe_name}.pdf"
        target_path = target_dir / safe_name
        target_path.write_bytes(content)
        return safe_name

    def delete_source(self, source_id: str) -> bool:
        """Delete a source file. Returns True if found.
        Call load_document(force=True) afterward to rebuild in-memory state."""
        if source_id not in set(self._source_files):
            return False
        source_path = self.settings.source_pdf_dir / source_id
        if source_path.exists():
            source_path.unlink()
        self._selected_sources.discard(source_id)
        return True

    def list_documents(self) -> list[dict]:
        """Return document-level summary for knowledge base management."""
        doc_map: dict[str, list[DocumentChunk]] = {}
        for chunk in self._chunks:
            doc_map.setdefault(chunk.source_id, []).append(chunk)

        result = []
        for source_id in self._source_files:
            chunks = doc_map.get(source_id, [])
            pages = [c.page_number for c in chunks if c.page_number is not None]
            page_range = f"{min(pages)}-{max(pages)}" if pages else "N/A"
            preview = chunks[0].text[:200] if chunks else ""
            result.append({
                "source_id": source_id,
                "chunk_count": len(chunks),
                "page_range": page_range,
                "text_preview": preview,
            })
        return result

    def get_document_chunks(self, source_id: str) -> list[dict]:
        """Return all chunks for a specific source file."""
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
        """返回文档摄入服务的当前状态摘要。"""
        return {
            "source_pdf_dir": str(self.settings.source_pdf_dir),
            "source_files": list(self._source_files),
            "selected_sources": sorted(self._selected_sources),
            "document_count": len(self._source_files),
            "document_loaded": bool(self._chunks),
            "chunk_count": len(self._chunks),
            "last_loaded_at": self._last_loaded_at,
            "warnings": list(self._warnings),
        }
