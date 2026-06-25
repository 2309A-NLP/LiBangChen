from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


"""
检索器预热状态跟踪模块。

提供线程安全的预热进度查询，供前端轮询显示加载状态。
"""


class WarmupStatusService:
    """线程安全的预热状态管理器，跟踪检索器预热的 idle → running → ready/failed 生命周期。"""
    def __init__(self) -> None:
        self._lock = Lock()
        self._state = {
            "status": "idle",
            "message": "not_started",
            "selected_only": False,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

    def start(self, *, selected_only: bool, message: str) -> None:
        with self._lock:
            self._state = {
                "status": "running",
                "message": message,
                "selected_only": selected_only,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "error": None,
            }

    def succeed(self, message: str) -> None:
        with self._lock:
            self._state["status"] = "ready"
            self._state["message"] = message
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._state["error"] = None

    def fail(self, message: str, error: str) -> None:
        with self._lock:
            self._state["status"] = "failed"
            self._state["message"] = message
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._state["error"] = error

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)
