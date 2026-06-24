from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

from app.core.config import Settings
from app.services.retrievers.lightrag import LightRAGIndexer


PRESERVED_WORKING_DIR_FILES = {".env", ".env.example"}


def discover_pdfs(pdf_dir: Path, explicit_pdfs: list[Path]) -> list[Path]:
    if explicit_pdfs:
        return [path for path in explicit_pdfs if path.exists() and path.suffix.lower() == ".pdf"]
    if not pdf_dir.exists():
        return []
    return sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())


def clean_working_dir(working_dir: Path) -> list[str]:
    removed: list[str] = []
    if not working_dir.exists():
        working_dir.mkdir(parents=True, exist_ok=True)
        return removed
    for child in working_dir.iterdir():
        if child.name in PRESERVED_WORKING_DIR_FILES:
            continue
        removed.append(str(child))
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return removed


def backup_working_dir(working_dir: Path) -> str | None:
    if not working_dir.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = working_dir.with_name(f"{working_dir.name}-backup-{timestamp}")
    shutil.copytree(working_dir, backup_path)
    return str(backup_path)


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or validate a LightRAG graph index.")
    parser.add_argument("--pdf-dir", type=Path, default=None, help="Directory containing source PDFs")
    parser.add_argument("--pdf", action="append", type=Path, default=[], help="Explicit PDF path")
    parser.add_argument("--sample-pages", type=int, default=None, help="Only index first N pages per PDF")
    parser.add_argument("--clean", action="store_true", help="Clean LightRAG working_dir before indexing")
    parser.add_argument("--backup", action="store_true", help="Backup LightRAG working_dir after indexing")
    parser.add_argument("--force-rebuild", action="store_true", help="Ignore index status and insert documents")
    parser.add_argument("--validate-query", action="append", default=[], help="Validation query")
    parser.add_argument("--report", type=Path, default=Path("reports/lightrag_index_report.json"))
    args = parser.parse_args()

    settings = Settings()
    lightrag_settings = settings.lightrag
    pdf_dir = args.pdf_dir or settings.source_pdf_dir
    working_dir = Path(lightrag_settings.working_dir)
    pdfs = discover_pdfs(pdf_dir, args.pdf)
    if not pdfs:
        raise SystemExit(f"No PDF files found in {pdf_dir}")

    report: dict[str, Any] = {
        "pdfs": [str(path) for path in pdfs],
        "working_dir": str(working_dir),
        "sample_pages": args.sample_pages,
        "cleaned_paths": [],
        "index_status": None,
        "validation": [],
        "backup_path": None,
    }

    if args.clean:
        report["cleaned_paths"] = clean_working_dir(working_dir)

    indexer = LightRAGIndexer(lightrag_settings)
    try:
        status = indexer.index_documents(
            pdfs,
            force_rebuild=args.force_rebuild or args.clean,
            max_pages_per_pdf=args.sample_pages,
        )
        report["index_status"] = status.model_dump()
        if args.validate_query:
            report["validation"] = indexer.validate_sample(args.validate_query)
    finally:
        indexer.close()

    if args.backup:
        report["backup_path"] = backup_working_dir(working_dir)

    write_report(report, args.report)
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
