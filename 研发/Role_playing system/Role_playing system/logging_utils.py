# -*- coding: utf-8 -*-
"""Shared logging configuration for the project."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
DEFAULT_LOG_PATH = LOG_DIR / "app.log"

_STREAM_HANDLER_NAME = "roleplay_stream_handler"
_FILE_HANDLER_NAME = "roleplay_file_handler"


def _has_handler(logger: logging.Logger, handler_name: str) -> bool:
    """Return True when the root logger already has the named handler."""
    return any(getattr(handler, "_roleplay_handler_name", None) == handler_name for handler in logger.handlers)


def configure_logging(log_path: Path | None = None) -> logging.Logger:
    """Configure process-wide logging once and return the root logger."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not _has_handler(root_logger, _STREAM_HANDLER_NAME):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler._roleplay_handler_name = _STREAM_HANDLER_NAME
        root_logger.addHandler(stream_handler)

    target_path = log_path or DEFAULT_LOG_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not _has_handler(root_logger, _FILE_HANDLER_NAME):
        file_handler = RotatingFileHandler(
            target_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._roleplay_handler_name = _FILE_HANDLER_NAME
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a named logger after ensuring shared logging is ready."""
    configure_logging()
    return logging.getLogger(name)
