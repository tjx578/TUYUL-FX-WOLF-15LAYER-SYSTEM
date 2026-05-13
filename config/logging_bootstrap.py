"""Shared process logging bootstrap for Railway services.

This module standardizes Loguru routing and applies lightweight limiters
so repeated or collectively noisy log lines do not flood platform logs.
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


class LogRateLimiter:
    """Aggregate fixed-window limiter used to protect platform log budgets."""

    def __init__(self, max_per_window: int, window_seconds: float) -> None:
        super().__init__()
        self._max_per_window = max(1, int(max_per_window))
        self._window_seconds = max(0.1, float(window_seconds))
        self._lock = threading.Lock()
        self._bucket = _Bucket(window_start=time.monotonic(), emitted=0)

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if (now - self._bucket.window_start) >= self._window_seconds:
                self._bucket = _Bucket(window_start=now, emitted=1)
                return True

            if self._bucket.emitted < self._max_per_window:
                self._bucket.emitted += 1
                return True

            return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_railway_runtime() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RAILWAY_REPLICA_ID")
    )


def _is_production_like() -> bool:
    app_env = os.getenv("APP_ENV", os.getenv("ENV", "")).strip().lower()
    return app_env == "production" or _is_railway_runtime()


def resolve_log_level(level: str | None = None) -> str:
    raw = level if level is not None else os.getenv("WOLF15_LOG_LEVEL")
    if raw:
        candidate = raw.upper().strip()
        if candidate in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
            return candidate
    return "WARNING" if _is_production_like() else "INFO"


def resolve_stdlib_log_level(level: str | None = None) -> int:
    resolved = resolve_log_level(level)
    if resolved in {"TRACE", "DEBUG"}:
        return 10
    if resolved in {"INFO", "SUCCESS"}:
        return 20
    if resolved == "WARNING":
        return 30
    if resolved == "ERROR":
        return 40
    if resolved == "CRITICAL":
        return 50
    return 20


def configure_loguru_logging(level: str | None = None) -> None:
    """Configure Loguru handlers with stdout/stderr split and burst limiting.

    Environment variables:
    - WOLF15_LOG_LEVEL: global minimum level (default: WARNING on Railway/prod, INFO elsewhere)
    - WOLF15_LOG_BURST_LIMIT: max identical log lines per window (default: 20)
    - WOLF15_LOG_BURST_WINDOW_SEC: window length in seconds (default: 1)
    - WOLF15_LOG_BURST_ENABLED: enable/disable limiter (default: true)
    - WOLF15_LOG_RATE_LIMIT: max total log lines per window (default: 30)
    - WOLF15_LOG_RATE_WINDOW_SEC: total log-rate window length in seconds (default: 1)
    - WOLF15_LOG_RATE_LIMIT_ENABLED: enable/disable aggregate limiter
      (default: true on Railway/prod, false elsewhere)
    - WOLF15_LOG_ENQUEUE: route logs through multiprocessing queue (default: false)
    """
    resolved_level = resolve_log_level(level)
    burst_enabled = _env_bool("WOLF15_LOG_BURST_ENABLED", True)
    rate_enabled = _env_bool("WOLF15_LOG_RATE_LIMIT_ENABLED", _is_production_like())
    enqueue_enabled = _env_bool("WOLF15_LOG_ENQUEUE", False)
    burst_limit = int(os.getenv("WOLF15_LOG_BURST_LIMIT", "20"))
    burst_window = float(os.getenv("WOLF15_LOG_BURST_WINDOW_SEC", "1.0"))
    rate_limit = int(os.getenv("WOLF15_LOG_RATE_LIMIT", "30"))
    rate_window = float(os.getenv("WOLF15_LOG_RATE_WINDOW_SEC", "1.0"))

    burst_limiter = LogBurstLimiter(max_per_window=burst_limit, window_seconds=burst_window)
    rate_limiter = LogRateLimiter(max_per_window=rate_limit, window_seconds=rate_window)

    def _allowed(record: Mapping[str, Any]) -> bool:
        if burst_enabled and not burst_limiter.allow(
            logger_name=str(record.get("name", "")),
            level_name=str(record["level"].name),
            message=str(record.get("message", "")),
        ):
            return False
        if rate_enabled and not rate_limiter.allow():
            return False
        return True

    loguru_logger.remove()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Route DEBUG/INFO/SUCCESS -> stdout, WARNING/ERROR/CRITICAL -> stderr.
    # Railway and most platform log collectors tag stdout as severity=info and
    # stderr as severity=error/warning, so this split is what drives correct
    # severity labelling in the log aggregator (the loguru text format itself
    # is not parsed for level by the collector).
    # WARNING_LEVEL_NO = 30 per loguru defaults.
    _WARNING_LEVEL_NO = 30  # noqa: N806

    def _add_handler(sink: Any, *, level_name: str, filter_fn: Any) -> None:
        try:
            loguru_logger.add(
                sink,
                format=log_format,
                level=level_name,
                filter=filter_fn,
                enqueue=enqueue_enabled,
            )
        except (OSError, PermissionError):
            if not enqueue_enabled:
                raise
            loguru_logger.add(
                sink,
                format=log_format,
                level=level_name,
                filter=filter_fn,
                enqueue=False,
            )

    _add_handler(
        sys.stdout,
        level_name=resolved_level,
        filter_fn=lambda record: record["level"].no < _WARNING_LEVEL_NO and _allowed(record),
    )
    _add_handler(
        sys.stderr,
        level_name="WARNING",
        filter_fn=lambda record: _allowed(record),
    )
