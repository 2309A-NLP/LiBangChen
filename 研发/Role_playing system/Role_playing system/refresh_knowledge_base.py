# -*- coding: utf-8 -*-
"""Refresh the public knowledge base and regenerate the PDF export."""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from knowledge_sync_service import sync_knowledge_documents
from models import KnowledgeDocument, SessionLocal, init_database


SYSTEM_ROLES = [
    "lawyer",
    "stock_analyst",
    "teacher",
    "psychological_counselor",
    "doctor",
    "scientist",
]


def backup_database() -> Optional[Path]:
    """Create a timestamped SQLite backup when the local DB file exists."""
    db_path = Path("roleplay_system.db")
    if not db_path.exists():
        return None

    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"roleplay_system_before_refresh_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def clear_system_knowledge() -> int:
    """Remove existing built-in knowledge rows before a full refresh."""
    db = SessionLocal()
    try:
        deleted = (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.role_type.in_(SYSTEM_ROLES))
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted
    finally:
        db.close()


def refresh_knowledge() -> None:
    """Rebuild the public knowledge base and its exported PDF."""
    init_database()

    backup_path = backup_database()
    if backup_path:
        print(f"已备份数据库: {backup_path}")

    deleted = clear_system_knowledge()
    print(f"已清空系统角色知识: {deleted} 条")

    result = sync_knowledge_documents()
    print(f"已生成 PDF 知识库: {result['pdf_path']}")
    print(f"已写入知识: {result['added_count']} 条")
    print(f"处理后的知识条目: {result['processed_count']} 条")


if __name__ == "__main__":
    refresh_knowledge()
