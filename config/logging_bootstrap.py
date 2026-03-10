"""Shared process logging bootstrap for Railway services.

This module standardizes Loguru routing and applies a lightweight
burst limiter so repeated identical log lines do not flood platform logs.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger as loguru_logger


@dataclass(slots=True)
class _Bucket:
    window_start: float
    emitted: int


class LogBurstLimiter:
    """Per-message sliding window limiter used by Loguru filters."""

    def __init__(self, max_per_window: int, window_seconds: float) -> None:
        super().__init__()
        self._max_per_window = max(1, int(max_per_window))
        self._window_seconds = max(0.1, float(window_seconds))
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str, str], _Bucket] = {}

    def allow(self, logger_name: str, level_name: str, message: str) -> bool:
        key = (logger_name, level_name, message)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or (now - bucket.window_start) >= self._window_seconds:
                self._buckets[key] = _Bucket(window_start=now, emitted=1)
                return True

            if bucket.emitted < self._max_per_window:
                bucket.emitted += 1
                return True

            return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_loguru_logging(level: str | None = None) -> None:
    """Configure Loguru handlers with stdout/stderr split and burst limiting.

    Environment variables:
    - WOLF15_LOG_LEVEL: global minimum level (default: INFO)
    - WOLF15_LOG_BURST_LIMIT: max identical log lines per window (default: 20)
    - WOLF15_LOG_BURST_WINDOW_SEC: window length in seconds (default: 1)
    - WOLF15_LOG_BURST_ENABLED: enable/disable limiter (default: true)
    """
    resolved_level = (level or os.getenv("WOLF15_LOG_LEVEL", "INFO")).upper().strip() or "INFO"
    burst_enabled = _env_bool("WOLF15_LOG_BURST_ENABLED", True)
    burst_limit = int(os.getenv("WOLF15_LOG_BURST_LIMIT", "20"))
    burst_window = float(os.getenv("WOLF15_LOG_BURST_WINDOW_SEC", "1.0"))

    limiter = LogBurstLimiter(max_per_window=burst_limit, window_seconds=burst_window)

    def _allowed(record: Mapping[str, Any]) -> bool:
        if not burst_enabled:
            return True
        return limiter.allow(
            logger_name=str(record.get("name", "")),
            level_name=str(record["level"].name),
            message=str(record.get("message", "")),
        )

    loguru_logger.remove()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    loguru_logger.add(
        sys.stdout,
        format=log_format,
        level=resolved_level,
        filter=lambda record: record["level"].no < 40 and _allowed(record),
        enqueue=True,
    )
    loguru_logger.add(
        sys.stderr,
        format=log_format,
        level="ERROR",
        filter=lambda record: _allowed(record),
        enqueue=True,
    )
