from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PyPDF2 import PdfReader

from config import KNOWLEDGE_SOURCE_CONFIG, PUBLIC_KNOWLEDGE_CHUNK_CONFIG, ROLES
from data_crawler import DataCrawler
from data_processor import DataProcessor

SYSTEM_ROLE_TYPES = tuple(role for role in ROLES.keys() if role != "custom_persona")


def get_knowledge_source_root() -> Path:
    return Path(KNOWLEDGE_SOURCE_CONFIG["root_dir"]).resolve()


def ensure_knowledge_source_directories() -> Dict[str, str]:
    root = get_knowledge_source_root()
    root.mkdir(parents=True, exist_ok=True)
    directories: Dict[str, str] = {}
    for role_type in SYSTEM_ROLE_TYPES:
        role_dir = root / role_type
        role_dir.mkdir(parents=True, exist_ok=True)
        directories[role_type] = str(role_dir)
    return directories


def get_knowledge_source_status() -> Dict[str, Any]:
    ensure_knowledge_source_directories()
    root = get_knowledge_source_root()
    scan_extensions = {
        str(ext).lower()
        for ext in KNOWLEDGE_SOURCE_CONFIG.get("scan_extensions", {".pdf"})
        if str(ext).strip()
    }

    role_directories: Dict[str, Dict[str, Any]] = {}
    total_files = 0
    for role_type in SYSTEM_ROLE_TYPES:
        role_dir = root / role_type
        files = [
            path
            for path in sorted(role_dir.iterdir())
            if path.is_file() and path.suffix.lower() in scan_extensions
        ]
        total_files += len(files)
        role_directories[role_type] = {
            "path": str(role_dir),
            "file_count": len(files),
            "files": [item.name for item in files],
        }

    return {
        "root_dir": str(root),
        "scan_extensions": sorted(scan_extensions),
        "include_seed_data": bool(KNOWLEDGE_SOURCE_CONFIG.get("include_seed_data", True)),
        "local_pdf_count": total_files,
        "role_directories": role_directories,
    }


def collect_knowledge_documents() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    ensure_knowledge_source_directories()
    seed_documents = DataCrawler().crawl_all_data() if KNOWLEDGE_SOURCE_CONFIG.get("include_seed_data", True) else []
    local_documents, local_errors = load_local_pdf_documents()
    status = get_knowledge_source_status()
    local_chunks = build_knowledge_vector_documents(local_documents)
    status.update(
        {
            "seed_document_count": len(seed_documents),
            "local_document_count": len(local_documents),
            "local_chunk_count": len(local_chunks),
            "errors": local_errors,
        }
    )
    return [*seed_documents, *local_documents], status


def load_local_pdf_documents() -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    processor = DataProcessor()
    root = get_knowledge_source_root()
    scan_extensions = {
        str(ext).lower()
        for ext in KNOWLEDGE_SOURCE_CONFIG.get("scan_extensions", {".pdf"})
        if str(ext).strip()
    }
    documents: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for role_type in SYSTEM_ROLE_TYPES:
        role_dir = root / role_type
        for pdf_path in sorted(role_dir.iterdir()):
            if not pdf_path.is_file() or pdf_path.suffix.lower() not in scan_extensions:
                continue
            if _should_skip_local_pdf(pdf_path):
                errors.append(
                    {
                        "file": str(pdf_path),
                        "role_type": role_type,
                        "error": "skipped internal generated pdf",
                    }
                )
                continue

            try:
                relative_path = pdf_path.relative_to(root).as_posix()
                sidecar_entries = _load_pdf_entries_sidecar(pdf_path, role_type, relative_path, processor)
                if sidecar_entries:
                    documents.extend(sidecar_entries)
                    continue

                content = _parse_pdf_file(pdf_path, processor)
                if _is_garbled_local_pdf(content):
                    errors.append(
                        {
                            "file": str(pdf_path),
                            "role_type": role_type,
                            "error": "skipped garbled local pdf content",
                        }
                    )
                    continue
                metadata = _load_pdf_sidecar_metadata(pdf_path)
                title = processor.clean_text(str(metadata.get("title") or "")) or pdf_path.stem
                source = processor.clean_text(
                    str(
                        metadata.get("source")
                        or metadata.get("landing_page_url")
                        or metadata.get("pdf_url")
                        or f"pdf://{relative_path}"
                    )
                ) or f"pdf://{relative_path}"
                documents.append(
                    {
                        "title": title,
                        "content": content,
                        "source": source,
                        "role_type": role_type,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "file": str(pdf_path),
                        "role_type": role_type,
                        "error": str(exc),
                    }
                )

    return documents, errors


def build_knowledge_vector_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processor = DataProcessor()
    chunk_size = int(PUBLIC_KNOWLEDGE_CHUNK_CONFIG["chunk_size"])
    chunk_overlap = int(PUBLIC_KNOWLEDGE_CHUNK_CONFIG["chunk_overlap"])
    vector_documents: List[Dict[str, Any]] = []
    for document in documents:
        vector_documents.extend(
            processor.build_chunked_documents(
                document,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return vector_documents


def _should_skip_local_pdf(pdf_path: Path) -> bool:
    name = pdf_path.name.lower()
    return name == "seed_roleplay_knowledge_base.pdf"


def _load_pdf_sidecar_metadata(pdf_path: Path) -> Dict[str, Any]:
    sidecar_path = pdf_path.with_suffix(".json")
    if not sidecar_path.exists():
        return {}
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_pdf_entries_sidecar(
    pdf_path: Path,
    role_type: str,
    relative_path: str,
    processor: DataProcessor,
) -> List[Dict[str, Any]]:
    sidecar_candidates = [
        pdf_path.with_name(pdf_path.stem.replace("_compendium", "_entries") + ".jsonl"),
        pdf_path.with_suffix(".jsonl"),
    ]
    sidecar_path = next((path for path in sidecar_candidates if path.exists()), None)
    if sidecar_path is None:
        return []

    documents: List[Dict[str, Any]] = []
    pdf_source = f"pdf://{relative_path}"
    with sidecar_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue

            title = processor.clean_text(str(payload.get("title") or "")) or f"{pdf_path.stem} [{index}]"
            content = processor.clean_text(str(payload.get("content") or ""))
            original_source = processor.clean_text(str(payload.get("source") or ""))
            if not content:
                continue
            source = pdf_source if not original_source else f"{pdf_source}；原始来源：{original_source}"
            documents.append(
                {
                    "title": title,
                    "content": content,
                    "source": source,
                    "role_type": role_type,
                }
            )
    return documents


def _parse_pdf_file(pdf_path: Path, processor: DataProcessor) -> str:
    reader = PdfReader(io.BytesIO(pdf_path.read_bytes()))
    parts: List[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = processor.clean_text(page.extract_text() or "")
        if page_text:
            parts.append(f"page {page_index}\n{page_text}")

    if not parts:
        raise ValueError(f"no extractable text found in {pdf_path.name}")

    return "\n\n".join(parts)


def _is_garbled_local_pdf(content: str) -> bool:
    cleaned = str(content or "").strip()
    if not cleaned:
        return True

    meaningful_chars = re.findall(r"[\u4e00-\u9fffa-zA-Z0-9]", cleaned)
    if not meaningful_chars:
        return True

    chinese_chars = re.findall(r"[\u4e00-\u9fff]", cleaned)
    chinese_ratio = len(chinese_chars) / max(len(meaningful_chars), 1)
    junk_tokens = re.findall(r"[A-Za-z0-9_/%:=()\\-]{8,}", cleaned)

    return chinese_ratio < 0.25 and len(junk_tokens) >= 5
