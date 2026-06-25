from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


class DocumentTaskService:
    """Thread-safe upload parsing task tracker."""

    def __init__(self, max_tasks: int = 50) -> None:
        self._lock = Lock()
        self._tasks: dict[str, dict[str, object]] = {}
        self._max_tasks = max_tasks

    def create_task(self, uploaded_files: list[str]) -> dict[str, object]:
        task_id = f"task-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        task = {
            "task_id": task_id,
            "status": "pending",
            "uploaded_files": list(uploaded_files),
            "processed_files": 0,
            "total_files": 0,
            "current_file": None,
            "current_step": "queued",
            "message": "Upload accepted. Parsing will continue in background.",
            "error": None,
            "selected_sources": [],
            "chunk_count": 0,
            "warnings": [],
            "created_at": now,
            "started_at": None,
            "finished_at": None,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._trim_locked()
            return dict(task)

    def start(self, task_id: str, *, total_files: int, message: str) -> None:
        with self._lock:
            task = self._require_task_locked(task_id)
            task["status"] = "processing"
            task["total_files"] = total_files
            task["current_step"] = "starting"
            task["message"] = message
            task["started_at"] = datetime.now(timezone.utc).isoformat()
            task["finished_at"] = None
            task["error"] = None

    def update(
        self,
        task_id: str,
        *,
        processed_files: int | None = None,
        total_files: int | None = None,
        current_file: str | None = None,
        current_step: str | None = None,
        message: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        with self._lock:
            task = self._require_task_locked(task_id)
            if processed_files is not None:
                task["processed_files"] = processed_files
            if total_files is not None:
                task["total_files"] = total_files
            if current_file is not None:
                task["current_file"] = current_file
            if current_step is not None:
                task["current_step"] = current_step
            if message is not None:
                task["message"] = message
            if warnings is not None:
                task["warnings"] = list(warnings)

    def succeed(
        self,
        task_id: str,
        *,
        processed_files: int,
        total_files: int,
        current_step: str,
        message: str,
        selected_sources: list[str],
        chunk_count: int,
        warnings: list[str],
    ) -> None:
        with self._lock:
            task = self._require_task_locked(task_id)
            task["status"] = "success"
            task["processed_files"] = processed_files
            task["total_files"] = total_files
            task["current_step"] = current_step
            task["message"] = message
            task["selected_sources"] = list(selected_sources)
            task["chunk_count"] = chunk_count
            task["warnings"] = list(warnings)
            task["finished_at"] = datetime.now(timezone.utc).isoformat()
            task["error"] = None

    def fail(
        self,
        task_id: str,
        *,
        current_step: str,
        message: str,
        error: str,
    ) -> None:
        with self._lock:
            task = self._require_task_locked(task_id)
            task["status"] = "failed"
            task["current_step"] = current_step
            task["message"] = message
            task["error"] = error
            task["finished_at"] = datetime.now(timezone.utc).isoformat()

    def get_task(self, task_id: str) -> dict[str, object]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            return dict(task)

    def _require_task_locked(self, task_id: str) -> dict[str, object]:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _trim_locked(self) -> None:
        while len(self._tasks) > self._max_tasks:
            oldest_key = next(iter(self._tasks))
            self._tasks.pop(oldest_key, None)
