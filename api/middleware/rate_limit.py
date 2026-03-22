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
  RATE_LIMIT_EA_CONTROL_PER_MIN   - EA restart/safe-mode (default 3)
  RATE_LIMIT_ACCOUNT_WRITE_PER_MIN - account create/update/delete (default 10)
  RATE_LIMIT_TRADE_WRITE_PER_MIN  - trade confirm/close/skip (default 20)
  RATE_LIMIT_RISK_CALC_PER_MIN    - /risk/calculate compute (default 30)
  RATE_LIMIT_ADMIN_PER_MIN        - destructive admin ops (default 5)
  RATE_LIMIT_EXEMPT_PATHS          - comma-separated extra paths to exempt (default "")
"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import parse_qs

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp
from typing_extensions import override

from infrastructure.redis_client import get_client

from .auth import decode_token, validate_api_key

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


def _default_rate_limit_backend() -> str:
    explicit = os.getenv("RATE_LIMIT_BACKEND")
    if explicit:
        return explicit.strip().lower()

    env = os.getenv("ENV", os.getenv("APP_ENV", "")).strip().lower()
    if env in {"prod", "production"}:
        return "redis"
    return "memory"


RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_BACKEND = _default_rate_limit_backend()  # memory | redis
if RATE_LIMIT_BACKEND not in {"memory", "redis"}:
    logger.warning(
        "Invalid RATE_LIMIT_BACKEND=%s; falling back to memory",
        RATE_LIMIT_BACKEND,
    )
    RATE_LIMIT_BACKEND = "memory"
REQUESTS_PER_MIN = _env_int("RATE_LIMIT_REQUESTS_PER_MIN", 120)
BURST = _env_int("RATE_LIMIT_BURST", 20)
WS_PER_MIN = _env_int("RATE_LIMIT_WS_PER_MIN", 10)
TAKE_PER_MIN = _env_int("RATE_LIMIT_TAKE_PER_MIN", 10)
CONFIG_WRITE_PER_MIN = _env_int("RATE_LIMIT_CONFIG_PER_MIN", 5)
WS_CONNECT_PER_MIN = _env_int("RATE_LIMIT_WS_CONNECT_PER_MIN", _env_int("WS_MAX_CONNECTIONS_PER_MIN", 10))
EA_CONTROL_PER_MIN = _env_int("RATE_LIMIT_EA_CONTROL_PER_MIN", 3)
ACCOUNT_WRITE_PER_MIN = _env_int("RATE_LIMIT_ACCOUNT_WRITE_PER_MIN", 10)
TRADE_WRITE_PER_MIN = _env_int("RATE_LIMIT_TRADE_WRITE_PER_MIN", 20)
RISK_CALC_PER_MIN = _env_int("RATE_LIMIT_RISK_CALC_PER_MIN", 30)
ADMIN_PER_MIN = _env_int("RATE_LIMIT_ADMIN_PER_MIN", 5)
RATE_LIMIT_REDIS_PREFIX = os.getenv("RATE_LIMIT_REDIS_PREFIX", "ratelimit:").strip() or "ratelimit:"
CLEANUP_INTERVAL_SEC = 120  # purge stale entries every N seconds

# Railway runs behind an internal proxy in the 100.64.0.0/10 CGNAT range.
# Auto-enable proxy trust when running on Railway so X-Forwarded-For is
# parsed and real client IPs are used for rate-limit identity.
_ON_RAILWAY = bool(
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RAILWAY_ENVIRONMENT_ID")
    or os.environ.get("RAILWAY_PROJECT_ID")
)
_RAILWAY_PROXY_CIDR = "100.64.0.0/10"
_default_proxies = "127.0.0.1,::1"
if _ON_RAILWAY:
    _default_proxies = f"127.0.0.1,::1,{_RAILWAY_PROXY_CIDR}"

_trusted_proxy_raw = os.getenv(
    "TRUSTED_PROXIES",
    os.getenv("RATE_LIMIT_TRUSTED_PROXY_IPS", _default_proxies),
)

# Parse trusted proxies — entries may be bare IPs or CIDR ranges.
_trusted_proxy_exact: set[str] = set()
_trusted_proxy_nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
TRUST_ALL_PROXIES = False
for _entry in _trusted_proxy_raw.split(","):
    _entry = _entry.strip()
    if not _entry:
        continue
    if _entry == "*":
        TRUST_ALL_PROXIES = True
        continue
    if "/" in _entry:
        try:
            _trusted_proxy_nets.append(ipaddress.ip_network(_entry, strict=False))
        except ValueError:
            logger.warning("Invalid CIDR in TRUSTED_PROXIES: %s", _entry)
    else:
        _trusted_proxy_exact.add(_entry)

TRUSTED_PROXY_ENABLED = _env_bool("TRUSTED_PROXY_ENABLED", _ON_RAILWAY)

if TRUSTED_PROXY_ENABLED and TRUST_ALL_PROXIES:
    logger.warning(
        "TRUSTED_PROXIES='*' trusts ALL proxies — "
        "X-Forwarded-For can be spoofed by any client. "
        "Set explicit proxy IPs in production."
    )

if _ON_RAILWAY and TRUSTED_PROXY_ENABLED:
    logger.info(
        "Railway detected — trusting proxies in %s for X-Forwarded-For",
        _RAILWAY_PROXY_CIDR,
    )

# Paths exempted from rate limiting (health, root).
EXEMPT_PATHS: set[str] = {"/", "/health", "/healthz", "/health/full", "/docs", "/openapi.json", "/redoc"}

# Merge user-defined exempt paths from env var.
_extra_exempt = os.getenv("RATE_LIMIT_EXEMPT_PATHS", "")
if _extra_exempt:
    _extra = {p.strip() for p in _extra_exempt.split(",") if p.strip()}
    EXEMPT_PATHS |= _extra
    logger.info("Rate-limit exempt paths extended: %s", _extra)


# ---------------------------------------------------------------------------
# Sliding window storage
# ---------------------------------------------------------------------------


@dataclass
class _ClientWindow:
    """Sliding-window timestamps for a single key."""

    timestamps: list[float] = field(default_factory=lambda: [])


class SlidingWindowStore:
    """Thread-safe sliding-window store keyed by a caller-provided identity."""

    def __init__(self, window_sec: int = 60) -> None:
        super().__init__()
        self._window = window_sec
        self._lock = threading.Lock()
        self._clients: dict[str, _ClientWindow] = defaultdict(_ClientWindow)
        self._last_cleanup = time.monotonic()

    def hit(self, identity_key: str) -> int:
        """
        Record a request and return the count within the current window.

        Returns:
            Number of requests in the current window (including this one).
        """
        now = time.monotonic()

        with self._lock:
            window = self._clients[identity_key]
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

    def get_count(self, identity_key: str) -> int:
        """Peek at the current window count without recording a hit."""
        now = time.monotonic()
        with self._lock:
            window = self._clients.get(identity_key)
            if not window:
                return 0
            cutoff = now - self._window
            return sum(1 for t in window.timestamps if t > cutoff)

    def _cleanup(self, now: float) -> None:
        """Remove IPs with no hits in the window (called under lock)."""
        cutoff = now - self._window
        stale_keys = [ip for ip, w in self._clients.items() if not w.timestamps or w.timestamps[-1] < cutoff]
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
_ea_control_store = SlidingWindowStore(window_sec=60)
_account_write_store = SlidingWindowStore(window_sec=60)
_trade_write_store = SlidingWindowStore(window_sec=60)
_risk_calc_store = SlidingWindowStore(window_sec=60)
_admin_store = SlidingWindowStore(window_sec=60)


def get_http_store() -> SlidingWindowStore:
    return _http_store


def get_ws_store() -> SlidingWindowStore:
    return _ws_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Forwarded-For only from trusted proxies.

    Uses the rightmost-untrusted strategy: walk the XFF chain from right to
    left and return the first IP that is NOT a trusted proxy.  This is safe
    against client-injected XFF headers because an attacker cannot forge IPs
    that appear *after* a trusted hop.
    """
    source_ip = request.client.host if request.client else "unknown"
    if not TRUSTED_PROXY_ENABLED:
        return source_ip

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not _is_trusted_proxy(source_ip):
        return source_ip

    # Walk from right (closest to server) to left (closest to client).
    # The first non-trusted IP is the real client.
    parts = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    for ip in reversed(parts):
        if not _is_trusted_proxy(ip):
            return ip

    # All IPs in the chain are trusted — use the leftmost as last resort.
    return parts[0] if parts else source_ip


def _is_trusted_proxy(source_ip: str) -> bool:
    if TRUST_ALL_PROXIES:
        return True
    if source_ip in _trusted_proxy_exact:
        return True
    if _trusted_proxy_nets:
        try:
            addr = ipaddress.ip_address(source_ip)
            return any(addr in net for net in _trusted_proxy_nets)
        except ValueError:
            pass
    return False


def _is_websocket(request: Request) -> bool:
    """Check if this is a WebSocket upgrade request."""
    upgrade = request.headers.get("upgrade", "").lower()
    return upgrade == "websocket"


_SAFE_KEY_RE = re.compile(r"[^a-zA-Z0-9_.:@=-]+")


def _safe_key_part(value: str | None, *, default: str = "na", max_len: int = 80) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return default
    cleaned = _SAFE_KEY_RE.sub("_", raw)
    return cleaned[:max_len] if cleaned else default


def _extract_token_from_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()

    if _is_websocket(request):
        q = parse_qs(request.url.query or "", keep_blank_values=False)
        ws_token = (q.get("token") or [""])[0].strip()
        if ws_token:
            return ws_token
    return None


def _resolve_actor_key(request: Request) -> str | None:
    token = _extract_token_from_request(request)
    if token:
        payload = decode_token(token)
        if payload is not None:
            subject = _safe_key_part(str(payload.get("sub") or "unknown"), default="unknown")
            return f"jwt:{subject}"
        if validate_api_key(token):
            return "api_key:api_key_user"
    return None


def _extract_path_account(path: str) -> str | None:
    path_clean = (path or "").strip("/")
    parts = [p for p in path_clean.split("/") if p]
    for idx, part in enumerate(parts):
        if part.lower() == "accounts" and (idx + 1) < len(parts):
            nxt = parts[idx + 1]
            if nxt and nxt.lower() not in {"take", "risk-snapshot", "capital-deployment"}:
                return nxt
    return None


def _extract_query_value(request: Request, *names: str) -> str | None:
    for name in names:
        val = request.query_params.get(name)
        if val and str(val).strip():
            return str(val).strip()
    return None


async def _extract_json_payload(request: Request) -> dict[str, object] | None:
    cached = getattr(request.state, "_rate_limit_json", None)
    if isinstance(cached, dict):
        return cached

    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        return None

    try:
        body = await request.body()
    except Exception:
        return None
    if not body:
        return None

    try:
        import json

        payload = json.loads(body)
    except Exception:
        return None

    if isinstance(payload, dict):
        request.state._rate_limit_json = payload
        return payload
    return None


async def _extract_account_and_ea_keys(request: Request) -> tuple[str | None, str | None]:
    account = _extract_query_value(request, "account_id", "account", "accountId") or _extract_path_account(
        request.url.path
    )
    ea = _extract_query_value(
        request,
        "ea_instance_id",
        "ea_instance",
        "ea_id",
        "agent_id",
        "instance_id",
    )

    if account and ea:
        return account, ea

    header_account = request.headers.get("x-account-id")
    if not account and header_account and header_account.strip():
        account = header_account.strip()

    header_ea = request.headers.get("x-ea-instance-id") or request.headers.get("x-agent-id")
    if not ea and header_ea and header_ea.strip():
        ea = header_ea.strip()

    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return account, ea

    payload = await _extract_json_payload(request)
    if payload is None:
        return account, ea

    if not account:
        for key in ("account_id", "account", "accountId"):
            raw = payload.get(key)
            if isinstance(raw, str) and raw.strip():
                account = raw.strip()
                break

    if not ea:
        for key in ("ea_instance_id", "ea_instance", "ea_id", "agent_id", "instance_id"):
            raw = payload.get(key)
            if isinstance(raw, str) and raw.strip():
                ea = raw.strip()
                break

    return account, ea


async def _identity_for_bucket(request: Request, bucket: str, client_ip: str) -> str:
    actor = _resolve_actor_key(request)
    account, ea_instance = await _extract_account_and_ea_keys(request)

    actor_part = _safe_key_part(actor, default="anon")
    ip_part = _safe_key_part(client_ip, default="unknown")
    account_part = _safe_key_part(account, default="none")
    ea_part = _safe_key_part(ea_instance, default="none")

    if bucket in {"take", "trade_write"}:
        return f"a={actor_part}|acct={account_part}|ea={ea_part}"
    if bucket in {"account_write", "risk_calc"}:
        return f"a={actor_part}|acct={account_part}"
    if bucket == "ea_control":
        return f"a={actor_part}|ea={ea_part}"
    if bucket in {"admin", "config_write"}:
        return f"a={actor_part}"
    if bucket in {"ws", "ws_connect"}:
        return f"a={actor_part}|ip={ip_part}"
    if actor:
        return f"a={actor_part}"
    return f"ip={ip_part}"


async def _redis_window_hit(key: str, ttl_sec: int = 60) -> int | None:
    """Atomic Redis INCR + EXPIRE for distributed rate limiting.

    Returns the current counter value, or None if Redis is unavailable.
    Falls back to None so callers use the in-memory store instead.
    """
    if RATE_LIMIT_BACKEND != "redis":
        return None
    try:
        client = await get_client()
        value = await client.incr(key)

        value_int: int
        if isinstance(value, int):
            value_int = value
        elif isinstance(value, str):
            value_int = int(value)
        elif isinstance(value, bytes | bytearray):
            value_int = int(value.decode())
        else:
            logger.debug(
                "Redis rate limit fallback for key={}: unsupported response type={}", key, type(value).__name__
            )
            return None

        if value_int == 1:
            await client.expire(key, ttl_sec)
        return value_int
    except Exception as exc:
        logger.debug("Redis rate limit fallback for key={}: {}", key, exc)
        return None


async def _check_bucket(
    bucket: str,
    identity_key: str,
    limit: int,
    fallback_store: SlidingWindowStore,
) -> tuple[bool, int]:
    slot = int(time.time() // 60)
    key = f"{RATE_LIMIT_REDIS_PREFIX}{bucket}:{identity_key}:{slot}"
    redis_count = await _redis_window_hit(key)
    if redis_count is not None:
        return redis_count <= limit, redis_count

    count = fallback_store.hit(identity_key)
    return count <= limit, count


def _path_bucket(path: str, method: str, is_ws_upgrade: bool) -> tuple[str, int, SlidingWindowStore] | None:
    lowered = path.lower()
    if is_ws_upgrade and "/ws" in lowered:
        return ("ws_connect", WS_CONNECT_PER_MIN, _ws_connect_store)

    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        # ── EA control (restart / safe-mode) — very tight ──
        # Paths are /api/v1/ea/restart, /api/v1/ea/safe-mode
        if "/ea/" in lowered and any(seg in lowered for seg in ("/restart", "/safe-mode")):
            return ("ea_control", EA_CONTROL_PER_MIN, _ea_control_store)

        # ── Trade take (original bucket) ──
        if (
            "/trades/take" in lowered
            or "/signals/take" in lowered
            or "/execution/take-signal" in lowered
            or ("/accounts/" in lowered and "/take" in lowered)
        ):
            return ("take", TAKE_PER_MIN, _take_store)

        # ── Trade lifecycle (confirm / close / skip) ──
        if any(
            seg in lowered
            for seg in (
                "/trades/confirm",
                "/trades/close",
                "/trades/skip",
                "/signals/skip",
            )
        ):
            return ("trade_write", TRADE_WRITE_PER_MIN, _trade_write_store)

        # ── Risk calculate (compute-heavy) ──
        if "/risk/calculate" in lowered:
            return ("risk_calc", RISK_CALC_PER_MIN, _risk_calc_store)

        # ── Account CRUD — paths are /api/v1/accounts/... ──
        if "/accounts" in lowered and method in {"POST", "PUT", "DELETE"}:
            return ("account_write", ACCOUNT_WRITE_PER_MIN, _account_write_store)

        # ── Config profile writes ──
        if "/config/profiles" in lowered:
            return ("config_write", CONFIG_WRITE_PER_MIN, _config_store)

        # ── Admin / destructive (redis candle delete, news-lock) ──
        if ("/redis/candles" in lowered and method == "DELETE") or "/news-lock/" in lowered:
            return ("admin", ADMIN_PER_MIN, _admin_store)

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

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.http_store = _http_store
        self.ws_store = _ws_store

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Never rate-limit CORS preflight — the CORSMiddleware handles these.
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Log WebSocket upgrade attempts to non-existent routes for diagnostics.
        # Starlette returns 403 for unmatched WS paths, which surfaces as
        # "connection rejected (403 Forbidden)" in websockets library logs.
        if _is_websocket(request):
            logger.debug(
                "WS upgrade attempt: path=%s origin=%s ip=%s",
                path,
                request.headers.get("origin", "-"),
                _client_ip(request),
            )

        if path in EXEMPT_PATHS:
            return await call_next(request)

        ip = _client_ip(request)

        bucket = _path_bucket(path, request.method.upper(), _is_websocket(request))
        if bucket is not None:
            bucket_name, bucket_limit, fallback_store = bucket
            identity_key = await _identity_for_bucket(request, bucket_name, ip)
            allowed, count = await _check_bucket(bucket_name, identity_key, bucket_limit, fallback_store)
            if not allowed:
                logger.warning(
                    "Rate limit exceeded: bucket=%s key=%s (%d/%d per min)",
                    bucket_name,
                    identity_key,
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
            ws_identity = await _identity_for_bucket(request, "ws", ip)
            allowed, count = await _check_bucket("ws", ws_identity, WS_PER_MIN, self.ws_store)
            if not allowed:
                logger.warning("WS rate limit exceeded: key=%s (%d/%d per min)", ws_identity, count, WS_PER_MIN)
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
        http_identity = await _identity_for_bucket(request, "http", ip)
        allowed, count = await _check_bucket("http", http_identity, limit, self.http_store)

        if not allowed:
            logger.warning("HTTP rate limit exceeded: key=%s (%d/%d per min)", http_identity, count, limit)
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
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))

        return response
