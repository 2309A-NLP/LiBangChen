from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from chat_bot import ChatBot
from data_processor import DataProcessor
from knowledge_pdf import KnowledgePdfExporter
from knowledge_sources import (
    build_knowledge_vector_documents,
    collect_knowledge_documents,
    ensure_knowledge_source_directories,
)
from models import KnowledgeDocument
from role_pdf_compendium import RolePdfCompendiumBuilder
from knowledge_pdf import build_pdf_knowledge_documents


def sync_knowledge_documents() -> Dict[str, Any]:
    ensure_knowledge_source_directories()
    source_documents, source_status = collect_knowledge_documents()
    processed_source_docs = DataProcessor().process_batch(source_documents)
    pdf_path = KnowledgePdfExporter().export(processed_source_docs)
    builder = RolePdfCompendiumBuilder()
    entries_by_role = builder.build_entries_by_role(processed_source_docs)
    role_pdf_result = builder.export(entries_by_role)
    entry_documents = []
    for role_type, entries in entries_by_role.items():
        role_pdf_path = role_pdf_result["roles"][role_type]["pdf_path"]
        entry_documents.extend(build_pdf_knowledge_documents(entries, pdf_path=Path(role_pdf_path)))
    vector_documents = build_knowledge_vector_documents(entry_documents)

    added_count = 0
    chat_bot = ChatBot()
    try:
        chat_bot.db.query(KnowledgeDocument).delete(synchronize_session=False)
        chat_bot.db.commit()

        for doc in vector_documents:
            created = chat_bot.add_knowledge_document(
                doc["title"],
                doc["content"],
                doc["source"],
                doc["role_type"],
                update_vector=False,
            )
            if created:
                added_count += 1

        if vector_documents:
            chat_bot.rag_chain.vector_store.replace_documents(vector_documents)
    finally:
        chat_bot.close()

    return {
        "source_document_count": len(source_documents),
        "processed_count": len(processed_source_docs),
        "entry_document_count": len(entry_documents),
        "vector_document_count": len(vector_documents),
        "added_count": added_count,
        "pdf_path": str(pdf_path),
        "role_pdf_compendiums": role_pdf_result,
        "knowledge_sources": source_status,
    }
