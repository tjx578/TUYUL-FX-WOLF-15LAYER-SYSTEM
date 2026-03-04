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

from storage.redis_client import redis_client

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
TAKE_PER_MIN = _env_int("RATE_LIMIT_TAKE_PER_MIN", 10)
CONFIG_WRITE_PER_MIN = _env_int("RATE_LIMIT_CONFIG_PER_MIN", 5)
WS_CONNECT_PER_MIN = _env_int("RATE_LIMIT_WS_CONNECT_PER_MIN", _env_int("WS_MAX_CONNECTIONS_PER_MIN", 10))
RATE_LIMIT_REDIS_PREFIX = os.getenv("RATE_LIMIT_REDIS_PREFIX", "ratelimit:").strip() or "ratelimit:"
CLEANUP_INTERVAL_SEC = 120  # purge stale entries every N seconds
_trusted_proxy_raw = os.getenv("RATE_LIMIT_TRUSTED_PROXY_IPS", "127.0.0.1,::1")
TRUSTED_PROXY_IPS = {ip.strip() for ip in _trusted_proxy_raw.split(",") if ip.strip()}
TRUST_ALL_PROXIES = "*" in TRUSTED_PROXY_IPS
TRUSTED_PROXY_ENABLED = _env_bool("TRUSTED_PROXY_ENABLED", False)

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
_take_store = SlidingWindowStore(window_sec=60)
_config_store = SlidingWindowStore(window_sec=60)
_ws_connect_store = SlidingWindowStore(window_sec=60)


def get_http_store() -> SlidingWindowStore:
    return _http_store


def get_ws_store() -> SlidingWindowStore:
    return _ws_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Forwarded-For only from trusted proxies."""
    source_ip = request.client.host if request.client else "unknown"
    if not TRUSTED_PROXY_ENABLED:
        return source_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(source_ip):
        # First entry is the original client
        return forwarded.split(",")[0].strip()
    return source_ip


def _is_trusted_proxy(source_ip: str) -> bool:
    if TRUST_ALL_PROXIES:
        return True
    return source_ip in TRUSTED_PROXY_IPS


def _is_websocket(request: Request) -> bool:
    """Check if this is a WebSocket upgrade request."""
    upgrade = request.headers.get("upgrade", "").lower()
    return upgrade == "websocket"


def _redis_window_hit(key: str, ttl_sec: int = 60) -> int | None:
    try:
        value = redis_client.client.incr(key)
        if int(value) == 1:
            redis_client.client.expire(key, ttl_sec)
        return int(value)
    except Exception as exc:
        logger.debug("Redis rate limit fallback for key=%s: %s", key, exc)
        return None


def _check_bucket(
    bucket: str,
    client_ip: str,
    limit: int,
    fallback_store: SlidingWindowStore,
) -> tuple[bool, int]:
    slot = int(time.time() // 60)
    key = f"{RATE_LIMIT_REDIS_PREFIX}{bucket}:{client_ip}:{slot}"
    redis_count = _redis_window_hit(key)
    if redis_count is not None:
        return redis_count <= limit, redis_count

    count = fallback_store.hit(client_ip)
    return count <= limit, count


def _path_bucket(path: str, method: str, is_ws_upgrade: bool) -> tuple[str, int, SlidingWindowStore] | None:
    lowered = path.lower()
    if is_ws_upgrade and lowered.startswith("/ws"):
        return ("ws_connect", WS_CONNECT_PER_MIN, _ws_connect_store)

    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        if "/trades/take" in lowered or "/signals/take" in lowered or "/accounts/" in lowered and "/take" in lowered:
            return ("take", TAKE_PER_MIN, _take_store)
        if "/config/profiles" in lowered:
            return ("config_write", CONFIG_WRITE_PER_MIN, _config_store)

    return None


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

        bucket = _path_bucket(path, request.method.upper(), _is_websocket(request))
        if bucket is not None:
            bucket_name, bucket_limit, fallback_store = bucket
            allowed, count = _check_bucket(bucket_name, ip, bucket_limit, fallback_store)
            if not allowed:
                logger.warning(
                    "Rate limit exceeded: bucket=%s ip=%s (%d/%d per min)",
                    bucket_name,
                    ip,
                    count,
                    bucket_limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Try again later.",
                        "bucket": bucket_name,
                        "retry_after_sec": 60,
                    },
                    headers={"Retry-After": "60"},
                )

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
