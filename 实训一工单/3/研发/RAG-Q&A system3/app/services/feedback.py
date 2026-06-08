from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import uuid

from app.schemas.query import FeedbackRequest


"""
用户反馈持久化模块。

将用户对问答结果的评分和评论以 JSONL 格式追加写入文件。
"""


class FeedbackService:
    """反馈服务：将用户反馈以 JSONL 格式持久化到本地文件。"""
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def save_feedback(self, payload: FeedbackRequest) -> dict[str, str]:
        record = {
            "feedback_id": str(uuid.uuid4()),
            "answer_id": payload.answer_id,
            "question": payload.question,
            "rating": payload.rating,
            "comment": payload.comment,
            "created_at": datetime.utcnow().isoformat(),
        }
        with self.store_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
