"""
App Factory — builds and configures the FastAPI application.

Responsible for:
  - Lifespan (Redis / Postgres init + teardown)
  - Middleware stack (CORS, Prometheus, rate-limit, security headers, HTTPS redirect)
  - Router mounting via router_registry
  - Duplicate-route guard
  - Dev/debug routes (gated by ENABLE_DEV_ROUTES)

Usage:
    from api.app_factory import create_app
    app = create_app()
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from typing_extensions import override

from api.middleware.auth import verify_token
from api.middleware.prometheus_middleware import PrometheusMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.router_registry import load_routers
from context.runtime_state import RuntimeState
from infrastructure.tracing import (
    instrument_asyncio,
    instrument_fastapi,
    instrument_httpx,
    instrument_redis,
    instrument_requests,
    setup_tracer,
)
from storage.postgres_client import pg_client

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _assert_no_duplicate_routes(application: FastAPI) -> None:
    """Raise RuntimeError at startup if any (method, path) pair is registered more than once."""
    seen: dict[tuple[str, str], str] = {}
    duplicates: list[str] = []

    for route in application.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        name = getattr(route, "name", "<unnamed>")
        if not methods or not path:
            continue
        for method in methods:
            key = (method.upper(), path)
            if key in seen:
                msg = f"DUPLICATE ROUTE: {method} {path} — handler '{name}' conflicts with '{seen[key]}'"
                duplicates.append(msg)
            else:
                seen[key] = name

    if duplicates:
        detail = "\n  ".join(duplicates)
        raise RuntimeError(
            f"Duplicate API endpoints detected ({len(duplicates)}):\n  {detail}\n"
            "Fix: remove one of the duplicate route definitions before starting."
        )


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("🐺 TUYUL FX Wolf-15 starting up…")
    from infrastructure.redis_client import close_pool, get_client
    from storage.trade_outbox_worker import TradeOutboxWorker

    # Guard Redis connection — app must start even if Redis is temporarily
    # unreachable so the /healthz probe can pass while infra catches up.
    try:
        app.state.redis = await get_client()
    except Exception:
        logger.warning("Redis unavailable at startup — will retry on first use")
        app.state.redis = None

    with suppress(Exception):
        await pg_client.initialize()

    outbox_worker: TradeOutboxWorker | None = None
    outbox_task: asyncio.Task[None] | None = None
    try:
        outbox_worker = TradeOutboxWorker(consumer_name="api-1")
        outbox_task = asyncio.create_task(outbox_worker.run(), name="trade-outbox-worker")
    except Exception:
        logger.warning("Trade outbox worker failed to start — will operate without outbox")
    app.state.trade_outbox_worker = outbox_worker
    app.state.trade_outbox_task = outbox_task

    # ── Cross-instance WS relay (Redis Pub/Sub) ──
    from infrastructure.cross_instance_relay import CrossInstanceRelay

    relay: CrossInstanceRelay | None = None
    if app.state.redis is not None and _env_bool("ENABLE_WS_RELAY", True):
        try:
            from api.ws_routes import (
                candle_manager,
                equity_manager,
                live_manager,
                pipeline_manager,
                price_manager,
                risk_manager,
                signal_manager,
                trade_manager,
                verdict_manager,
            )

            relay = CrossInstanceRelay(redis_client=app.state.redis)
            await relay.start(
                {
                    "prices": price_manager,
                    "trades": trade_manager,
                    "candles": candle_manager,
                    "risk": risk_manager,
                    "equity": equity_manager,
                    "verdict": verdict_manager,
                    "signals": signal_manager,
                    "pipeline": pipeline_manager,
                    "live": live_manager,
                }
            )
            app.state.ws_relay = relay
        except Exception:
            logger.warning("CrossInstanceRelay failed to start — single-instance mode")
            relay = None

    # ── Peer health checker (inter-service monitoring) ──
    from infrastructure.peer_health import PeerHealthChecker

    peer_checker: PeerHealthChecker | None = None
    if _env_bool("ENABLE_PEER_HEALTH", True):
        try:
            peer_checker = PeerHealthChecker(self_name="api")
            await peer_checker.start()
            app.state.peer_health_checker = peer_checker
        except Exception:
            logger.warning("PeerHealthChecker failed to start — fleet health unavailable")
            peer_checker = None

    try:
        yield
    finally:
        if peer_checker is not None:
            with suppress(Exception):
                await peer_checker.stop()
        if relay is not None:
            with suppress(Exception):
                await relay.stop()
        if outbox_worker is not None:
            with suppress(Exception):
                await outbox_worker.stop()
        if outbox_task is not None:
            with suppress(asyncio.CancelledError):
                outbox_task.cancel()
                await outbox_task
        with suppress(Exception):
            await pg_client.close()
        await close_pool()
        logger.info("🐺 TUYUL FX Wolf-15 shutting down…")


# ── Middleware helpers ────────────────────────────────────────────────────────


class ForwardedHTTPSRedirectMiddleware(BaseHTTPMiddleware):
    # Paths that must never be redirected (internal health probes, metrics).
    _EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/healthz", "/health/full", "/metrics"})

    def __init__(self, app: Any, force_https: bool) -> None:
        super().__init__(app)
        self.force_https = force_https

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.force_https:
            return await call_next(request)
        # Allow internal health probes through without redirect
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        # Proxy-safe HTTPS detection.
        # Some ingress layers send comma-separated values (e.g. "https,http")
        # or RFC-7239 Forwarded header with proto key.
        forwarded_proto_raw = request.headers.get("x-forwarded-proto", "")
        proto_tokens = {token.strip().lower() for token in forwarded_proto_raw.split(",") if token.strip()}

        forwarded_header = request.headers.get("forwarded", "").lower()
        if "proto=https" in forwarded_header:
            proto_tokens.add("https")

        is_https = request.url.scheme == "https" or "https" in proto_tokens

        if not is_https:
            return RedirectResponse(url=str(request.url.replace(scheme="https")), status_code=307)
        return await call_next(request)


def _add_cors(app: FastAPI) -> None:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8000,https://railway-dashboard-production-de97.up.railway.app",
    )
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    # Vercel preview/production URLs — add if set
    vercel_url = os.getenv("VERCEL_FRONTEND_URL", "")
    if vercel_url.strip():
        for u in vercel_url.split(","):
            u = u.strip().rstrip("/")
            if u and u not in origins:
                origins.append(u)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            deduped.append(o)
    origins = deduped
    logger.info("CORS allowed origins: %s", origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-Idempotency-Key",
        ],
        expose_headers=[],
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, csp_value: str) -> None:
        super().__init__(app)
        self.csp_value = csp_value

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers

        if "X-Content-Type-Options" not in headers:
            headers["X-Content-Type-Options"] = "nosniff"
        if "X-Frame-Options" not in headers:
            headers["X-Frame-Options"] = "SAMEORIGIN"
        if "Referrer-Policy" not in headers:
            headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if "Content-Security-Policy" not in headers:
            headers["Content-Security-Policy"] = self.csp_value

        return response


def _add_security_middleware(app: FastAPI, force_https: bool) -> None:
    _csp_domain = os.getenv("API_DOMAIN", "localhost")
    csp_default = f"default-src 'self'; connect-src 'self' https://{_csp_domain} wss://{_csp_domain};"
    csp_value = os.getenv("CSP_HEADER", csp_default)

    app.add_middleware(ForwardedHTTPSRedirectMiddleware, force_https=force_https)
    app.add_middleware(SecurityHeadersMiddleware, csp_value=csp_value)


# ── Dev / Debug routes ────────────────────────────────────────────────────────


def _register_dev_routes(app: FastAPI) -> None:
    """Register debug-only endpoints (disabled in production runtime)."""

    def _is_production_runtime() -> bool:
        env = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()
        return env == "production"

    async def debug_redis_keys() -> dict[str, Any]:
        if _is_production_runtime():
            raise HTTPException(status_code=404, detail="Not found")
        from infrastructure.redis_client import get_client

        try:
            r = await get_client()
            all_keys: list[bytes | str] = await r.keys("*")
            decoded = sorted(k if isinstance(k, str) else k.decode() for k in all_keys)
            prefixes: dict[str, int] = {}
            for k in decoded:
                prefix = k.split(":")[0] if ":" in k else k
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
            return {"total": len(decoded), "prefixes": prefixes, "keys": decoded[:100]}
        except Exception as exc:
            return {"error": str(exc)}

    async def endpoint_summary() -> dict[str, Any]:
        if _is_production_runtime():
            raise HTTPException(status_code=404, detail="Not found")
        routes: list[dict[str, Any]] = []
        for route in app.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                routes.append(
                    {
                        "path": getattr(route, "path", "unknown"),
                        "methods": list(route.methods),  # type: ignore[arg-type]
                        "name": getattr(route, "name", "unknown"),
                    }
                )

        def _sort_key(r: dict[str, Any]) -> str:
            p = r.get("path", "unknown")
            return p if isinstance(p, str) else "unknown"

        return {"total": len(routes), "routes": sorted(routes, key=_sort_key)}

    app.add_api_route("/debug/redis-keys", debug_redis_keys, methods=["GET"])
    app.add_api_route("/api/v1/endpoints", endpoint_summary, methods=["GET"])


# ── Health routes ─────────────────────────────────────────────────────────────


def _register_health_routes(app: FastAPI) -> None:
    async def root() -> dict[str, str]:
        return {
            "service": "tuyul-fx",
            "status": "ok",
            "health": "/health",
        }

    app.add_api_route("/", root, methods=["GET"])

    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/healthz", health, methods=["GET"])

    async def full_health(request: Request) -> dict[str, Any]:
        from datetime import UTC, datetime

        import redis.asyncio as aioredis

        from config_loader import CONFIG

        redis_ok = False
        with suppress(Exception):
            r: aioredis.Redis = request.app.state.redis
            ping_result: bool = await r.ping()  # type: ignore[assignment]
            redis_ok = ping_result is True

        postgres_health = await pg_client.health_check()
        config_loaded = bool(CONFIG.get("constitution"))
        engine_state = {
            "healthy": bool(RuntimeState.healthy),
            "latency_ms": int(RuntimeState.latency_ms),
            "session_hours": round(RuntimeState.get_session_hours(), 3),
        }

        lockdown_state = "unknown"
        with suppress(Exception):
            r = request.app.state.redis
            locked = await r.get("system:lockdown")
            lockdown_state = "locked" if str(locked).lower() in {"1", "true", "locked", "on"} else "normal"

        return {
            "status": "ok" if redis_ok and bool(postgres_health.get("connected")) else "degraded",
            "service": "tuyul-fx",
            "version": "10.0.0",
            "redis": {"connected": redis_ok},
            "postgres": postgres_health,
            "config_loaded": config_loaded,
            "engine_state": engine_state,
            "lockdown_state": lockdown_state,
            "mt5_connected": False,
            "active_pairs": 0,
            "active_trades": 0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    app.add_api_route(
        "/health/full",
        full_health,
        methods=["GET"],
        dependencies=[Depends(verify_token)],
    )


# ── Factory ───────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and return the fully-configured FastAPI application."""
    app_env = os.getenv("ENV", "development").strip().lower()
    is_production = app_env == "production"
    debug_mode = _env_bool("DEBUG", default=not is_production)
    enable_dev_routes = _env_bool("ENABLE_DEV_ROUTES", default=not is_production)

    if is_production:
        debug_mode = False
        enable_dev_routes = False

    force_https = _env_bool("FORCE_HTTPS", default=is_production)

    app = FastAPI(
        title="TUYUL FX — Wolf-15 API",
        version="10.0.0",
        description="Institutional-grade trading system API",
        lifespan=lifespan,
        debug=debug_mode,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
    )

    # Telemetry
    _tracer = setup_tracer("wolf-api")  # noqa: F841
    instrument_asyncio()
    instrument_redis()
    instrument_requests()
    instrument_httpx()
    instrument_fastapi(app)

    # Middleware stack
    _add_security_middleware(app, force_https)
    _add_cors(app)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # Mount all routers from the registry
    for router, description in load_routers():
        app.include_router(router)
        logger.debug("Mounted router: %s", description)

    # Guard: fail fast if any (method, path) was registered more than once.
    _assert_no_duplicate_routes(app)

    # Health endpoints
    _register_health_routes(app)

    # Dev routes (gated)
    if enable_dev_routes:
        _register_dev_routes(app)

    return app
