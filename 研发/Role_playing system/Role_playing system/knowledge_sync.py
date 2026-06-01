# -*- coding: utf-8 -*-
"""
知识同步调度模块
================
功能：提供知识库的定时同步调度功能。通过后台线程定期执行知识同步任务，
确保知识库内容与知识源目录保持同步。支持启动时立即执行和定时执行两种模式。

主要类：KnowledgeSyncManager
  - run_once(): 立即执行一次知识同步
  - start(): 启动后台定时同步线程
  - stop(): 停止后台同步线程
  - get_status(): 获取同步状态（上次运行时间、结果、错误等）
"""

import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from config import KNOWLEDGE_SYNC_CONFIG


class KnowledgeSyncManager:
    """
    知识同步管理器。
    
    通过后台线程定期执行知识同步任务，确保知识库内容与知识源目录保持同步。
    支持启动时立即执行和定时执行两种模式。
    """

    def __init__(self, sync_func: Callable[[], Dict[str, Any]]):
        """
        初始化知识同步管理器。
        
        Args:
            sync_func: 实际执行同步的回调函数，返回同步结果字典
        """
        self.sync_func = sync_func
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.status: Dict[str, Any] = {
            "enabled": KNOWLEDGE_SYNC_CONFIG["enabled"],
            "interval_minutes": KNOWLEDGE_SYNC_CONFIG["interval_minutes"],
            "run_on_startup": KNOWLEDGE_SYNC_CONFIG["run_on_startup"],
            "running": False,
            "last_run_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_result": None,
        }

    def run_once(self) -> Dict[str, Any]:
        """
        立即执行一次知识同步。
        
        使用线程锁确保同一时间只有一个同步任务在执行。
        
        Returns:
            Dict[str, Any]: 同步结果字典
            
        Raises:
            RuntimeError: 同步任务正在进行中
        """
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("知识同步正在进行中，请稍后再试")

        self.status["running"] = True
        self.status["last_run_at"] = datetime.now().isoformat()
        self.status["last_error"] = None

        try:
            result = self.sync_func()
            self.status["last_success_at"] = datetime.now().isoformat()
            self.status["last_result"] = result
            return result
        except Exception as exc:
            self.status["last_error"] = str(exc)
            raise
        finally:
            self.status["running"] = False
            self.lock.release()

    def start(self) -> None:
        """
        启动后台定时同步线程。
        
        如果同步未启用或线程已启动，则不执行任何操作。
        """
        if not self.status["enabled"] or self.thread is not None:
            return

        self.thread = threading.Thread(target=self._worker, name="knowledge-sync", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """
        停止后台同步线程。
        
        设置停止事件并等待线程退出（最多 2 秒）。
        """
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None

    def get_status(self) -> Dict[str, Any]:
        """
        获取同步状态。
        
        Returns:
            Dict[str, Any]: 包含 enabled, interval_minutes, running, 
                            last_run_at, last_success_at, last_error, last_result 等字段
        """
        return dict(self.status)

    def _worker(self) -> None:
        """
        后台工作线程主循环。
        
        如果配置了 run_on_startup，启动时立即执行一次同步。
        然后按 interval_minutes 间隔定时执行同步。
        """
        interval_seconds = max(int(self.status["interval_minutes"]) * 60, 60)

        if self.status["run_on_startup"] and not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self.status["last_error"] = str(exc)

        while not self.stop_event.wait(interval_seconds):
            try:
                self.run_once()
            except Exception as exc:
                self.status["last_error"] = str(exc)
