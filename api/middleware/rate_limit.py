"""
Rate Limiting Middleware -- per-IP sliding window.

Uses an in-memory sliding-window counter per client IP.
No external dependency required; state resets on restart (acceptable for
single-process deployments; use Redis-backed limiter for multi-instance).

Environment variables:
  RATE_LIMIT_REQUESTS_PER_MIN      - max requests per minute (default 120)
  RATE_LIMIT_BURST                 - burst tolerance above base (default 20)
  RATE_LIMIT_WS_PER_MIN           - WebSocket upgrade rate (default 10)
  RATE_LIMIT_ENABLED              - "true" / "false" (default "true")
"""

from __future__ import annotations

import os
import threading
import time

from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse  # pyright: ignore[reportMissingImports]
from loguru import logger  # pyright: ignore[reportMissingImports]
from starlette.middleware.base import BaseHTTPMiddleware  # pyright: ignore[reportMissingImports]
from starlette.types import ASGIApp  # pyright: ignore[reportMissingImports]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
REQUESTS_PER_MIN = _env_int("RATE_LIMIT_REQUESTS_PER_MIN", 120)
BURST = _env_int("RATE_LIMIT_BURST", 20)
WS_PER_MIN = _env_int("RATE_LIMIT_WS_PER_MIN", 10)
CLEANUP_INTERVAL_SEC = 120  # purge stale entries every N seconds

# Paths exempted from rate limiting (health, root).
EXEMPT_PATHS: set[str] = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


# ---------------------------------------------------------------------------
# Sliding window storage
# ---------------------------------------------------------------------------

@dataclass
class _ClientWindow:
    """Sliding-window timestamps for a single client IP."""
    timestamps: list[float] = field(default_factory=list)


class SlidingWindowStore:
    """Thread-safe per-IP sliding-window store."""

    def __init__(self, window_sec: int = 60):
        self._window = window_sec
        self._lock = threading.Lock()
        self._clients: dict[str, _ClientWindow] = defaultdict(_ClientWindow)
        self._last_cleanup = time.monotonic()

    def hit(self, client_ip: str) -> int:
        """
        Record a request and return the count within the current window.

        Returns:
            Number of requests in the current window (including this one).
        """
        now = time.monotonic()

        with self._lock:
            window = self._clients[client_ip]
            cutoff = now - self._window

            # Prune expired timestamps
            window.timestamps = [t for t in window.timestamps if t > cutoff]

            # Record current hit
            window.timestamps.append(now)

            count = len(window.timestamps)

            # Periodic cleanup of stale IPs
            if now - self._last_cleanup > CLEANUP_INTERVAL_SEC:
                self._cleanup(now)
                self._last_cleanup = now

        return count

    def get_count(self, client_ip: str) -> int:
        """Peek at the current window count without recording a hit."""
        now = time.monotonic()
        with self._lock:
            window = self._clients.get(client_ip)
            if not window:
                return 0
            cutoff = now - self._window
            return sum(1 for t in window.timestamps if t > cutoff)

    def _cleanup(self, now: float) -> None:
        """Remove IPs with no hits in the window (called under lock)."""
        cutoff = now - self._window
        stale_keys = [
            ip for ip, w in self._clients.items()
            if not w.timestamps or w.timestamps[-1] < cutoff
        ]
        for key in stale_keys:
            del self._clients[key]

    def reset(self) -> None:
        """Clear all state (useful for testing)."""
        with self._lock:
            self._clients.clear()


# Singleton stores
_http_store = SlidingWindowStore(window_sec=60)
_ws_store = SlidingWindowStore(window_sec=60)


def get_http_store() -> SlidingWindowStore:
    return _http_store


def get_ws_store() -> SlidingWindowStore:
    return _ws_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First entry is the original client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_websocket(request: Request) -> bool:
    """Check if this is a WebSocket upgrade request."""
    upgrade = request.headers.get("upgrade", "").lower()
    return upgrade == "websocket"


# ---------------------------------------------------------------------------
# FastAPI / Starlette middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP rate limiting middleware for HTTP and WebSocket upgrade requests.

    Separate limits for regular HTTP and WebSocket connections.
    Returns 429 Too Many Requests when limit is exceeded.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.http_store = _http_store
        self.ws_store = _ws_store

    async def dispatch(self, request: Request, call_next) -> Response:
        if not RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        ip = _client_ip(request)

        # WebSocket upgrade request
        if _is_websocket(request):
            count = self.ws_store.hit(ip)
            if count > WS_PER_MIN:
                logger.warning(
                    f"WS rate limit exceeded: {ip} ({count}/{WS_PER_MIN} per min)"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "WebSocket rate limit exceeded. Try again later.",
                        "retry_after_sec": 60,
                    },
                    headers={"Retry-After": "60"},
                )
            return await call_next(request)

        # Regular HTTP request
        limit = REQUESTS_PER_MIN + BURST
        count = self.http_store.hit(ip)

        if count > limit:
            logger.warning(
                f"HTTP rate limit exceeded: {ip} ({count}/{limit} per min)"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "retry_after_sec": 60,
                },
                headers={"Retry-After": "60"},
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(REQUESTS_PER_MIN)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, limit - count)
        )

        return response
