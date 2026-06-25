from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from data_crawler import DataCrawler
from knowledge_pdf import KnowledgePdfExporter
from knowledge_sources import build_knowledge_vector_documents
from models import KnowledgeDocument, SessionLocal, init_database
from role_pdf_compendium import RolePdfCompendiumBuilder
from vector_store import MilvusStore


ROLE_TYPE = "doctor"


def _build_clean_doctor_entries(target_count: int = 1000) -> List[Dict]:
    documents = [doc for doc in DataCrawler().crawl_doctor_data() if doc.get("role_type") == ROLE_TYPE]
    builder = RolePdfCompendiumBuilder(target_entries_per_role=target_count)
    entries_by_role = builder.build_entries_by_role(documents)
    return entries_by_role.get(ROLE_TYPE, [])


def _write_entries(entries: List[Dict]) -> Dict[str, str]:
    output_dir = Path("generated/domain_pdfs")
    output_dir.mkdir(parents=True, exist_ok=True)

    entries_path = output_dir / f"{ROLE_TYPE}_entries.jsonl"
    pdf_path = output_dir / f"{ROLE_TYPE}_compendium.pdf"

    with entries_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    KnowledgePdfExporter(str(pdf_path)).export(entries)
    return {
        "entries_path": str(entries_path.resolve()),
        "pdf_path": str(pdf_path.resolve()),
    }


def _replace_sqlite(documents: List[Dict]) -> int:
    db = SessionLocal()
    try:
        db.query(KnowledgeDocument).filter(KnowledgeDocument.role_type == ROLE_TYPE).delete(synchronize_session=False)
        payload = [
            KnowledgeDocument(
                title=document.get("title", ""),
                content=document.get("content", ""),
                source=document.get("source", ""),
                role_type=ROLE_TYPE,
            )
            for document in documents
        ]
        db.add_all(payload)
        db.commit()
        return len(payload)
    finally:
        db.close()


def _replace_milvus(documents: List[Dict]) -> Dict[str, object]:
    store = MilvusStore()
    result: Dict[str, object] = {
        "available": store.available,
        "degraded_reason": store.degraded_reason,
        "deleted": None,
        "inserted": 0,
    }
    if not store.available or store.collection is None:
        return result

    expr = f'role_type == "{ROLE_TYPE}"'
    before = store.collection.query(expr=expr, output_fields=["doc_id"], limit=16384)
    result["deleted"] = len(before)
    store.collection.delete(expr)
    store.collection.flush()

    if documents:
        store.insert_documents(documents)
        after = store.collection.query(expr=expr, output_fields=["doc_id"], limit=16384)
        result["inserted"] = len(after)
    return result


def main() -> None:
    init_database()
    entries = _build_clean_doctor_entries(target_count=1000)
    vector_documents = build_knowledge_vector_documents(entries)
    files = _write_entries(entries)
    sqlite_count = _replace_sqlite(vector_documents)
    milvus = _replace_milvus(vector_documents)


if __name__ == "__main__":
    main()
