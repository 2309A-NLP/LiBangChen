from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


class IngestionStatusService:
    """Thread-safe status tracker for document upload and parsing."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state = {
            "status": "idle",
            "message": "not_started",
            "source_files": [],
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

    def start(self, *, message: str, source_files: list[str] | None = None) -> None:
        with self._lock:
            self._state = {
                "status": "running",
                "message": message,
                "source_files": list(source_files or []),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "error": None,
            }

    def succeed(self, message: str, *, source_files: list[str] | None = None) -> None:
        with self._lock:
            self._state["status"] = "ready"
            self._state["message"] = message
            self._state["source_files"] = list(source_files or [])
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._state["error"] = None

    def fail(
        self,
        message: str,
        error: str,
        *,
        source_files: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._state["status"] = "failed"
            self._state["message"] = message
            self._state["source_files"] = list(source_files or [])
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._state["error"] = error

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)
