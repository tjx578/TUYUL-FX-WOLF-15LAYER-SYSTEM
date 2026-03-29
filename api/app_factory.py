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
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from typing_extensions import override

from api.middleware.machine_auth import verify_observability_machine_auth
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

from .middleware.auth import verify_token

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
    from infrastructure.redis_url import get_safe_redis_url
    from storage.trade_outbox_worker import TradeOutboxWorker

    # Log the resolved Redis URL (password masked) so operators can confirm that
    # both the API service and the Engine service are targeting the same Redis
    # instance (BUG #6 — RUN_MODE split-deployment Redis isolation).
    logger.info("[Redis] API service Redis target: %s", get_safe_redis_url())

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
                alerts_manager,
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
                    "alerts": alerts_manager,
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

    # ── HybridCandleAggregator (dual-zone display) ──
    from api.ws_routes import _candle_agg
    from config_loader import get_enabled_symbols

    _candle_agg_started = False
    try:
        _enabled_syms = [p.replace("/", "").upper() for p in get_enabled_symbols()]
        await _candle_agg.start(_enabled_syms)
        _candle_agg_started = True
    except Exception as exc:
        logger.warning("HybridCandleAggregator failed to start: %s — candle WS may be empty", exc)

    # ── Embedded Orchestrator (opt-in via WOLF15_EMBED_ORCHESTRATOR=true) ──
    _orchestrator_thread: threading.Thread | None = None
    if _env_bool("WOLF15_EMBED_ORCHESTRATOR", False):
        try:
            from services.orchestrator.state_manager import StateManager

            def _run_orchestrator() -> None:
                try:
                    StateManager().run_forever()
                except Exception:
                    logger.exception("Embedded orchestrator crashed")

            _orchestrator_thread = threading.Thread(
                target=_run_orchestrator,
                daemon=True,
                name="embedded-orchestrator",
            )
            _orchestrator_thread.start()
            logger.info("Embedded orchestrator started (daemon thread)")
        except Exception:
            logger.warning("Embedded orchestrator failed to start — running API-only")

    try:
        yield
    finally:
        if peer_checker is not None:
            with suppress(Exception):
                await peer_checker.stop()
        if _candle_agg_started:
            with suppress(Exception):
                await _candle_agg.stop()
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

        # Never redirect CORS preflight — browsers send OPTIONS over the
        # original scheme and won't follow a 307 redirect for preflight.
        if request.method.upper() == "OPTIONS":
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
    # Production should set CORS_ORIGINS explicitly. Keep fallback minimal and stable
    # so redeploy-specific hostnames (e.g., Railway-generated domains) are never baked in.
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000,https://tuyul-fx-dashboard.vercel.app")
    if "CORS_ORIGINS" not in os.environ:
        logger.warning(
            "CORS_ORIGINS not set; using fallback origins. Set CORS_ORIGINS explicitly in deployed services."
        )
    # Support both comma and newline separators (common in Vercel env var editor)
    raw_normalized = raw.replace("\n", ",").replace("\r", "")
    origins = [o.strip().rstrip("/") for o in raw_normalized.split(",") if o.strip()]
    # Vercel preview/production URLs — add if set
    vercel_url = os.getenv("VERCEL_FRONTEND_URL", "")
    if vercel_url.strip():
        for u in vercel_url.replace("\n", ",").split(","):
            u = u.strip().rstrip("/")
            if u and u not in origins:
                origins.append(u)
    # VERCEL_URL is set automatically by Vercel to the current deployment URL.
    # It does NOT include the scheme — prefix https:// if missing.
    auto_vercel_url = os.getenv("VERCEL_URL", "").strip().rstrip("/")
    if auto_vercel_url:
        full = auto_vercel_url if auto_vercel_url.startswith("http") else f"https://{auto_vercel_url}"
        if full not in origins:
            origins.append(full)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            deduped.append(o)
    origins = deduped
    logger.info("CORS effective origins (%d): %s", len(origins), origins)
    # Regex for dynamic origins (e.g. Vercel preview deployments).
    origin_regex = os.getenv("CORS_ORIGIN_REGEX", "").strip() or None
    if origin_regex:
        logger.info("CORS origin regex: %s", origin_regex)
    else:
        # Auto-derive regex for Vercel preview deployments from static origins.
        import re as _re

        _vercel_patterns: list[str] = []
        for o in origins:
            if o.endswith(".vercel.app"):
                _prefix = _re.escape(o.rsplit(".vercel.app", 1)[0])
                _vercel_patterns.append(f"{_prefix}(-[a-z0-9-]+)?\\.vercel\\.app")
        if _vercel_patterns:
            origin_regex = "|".join(_vercel_patterns)
            logger.info("CORS origin regex (auto-derived for Vercel previews): %s", origin_regex)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-Idempotency-Key",
            "X-Edit-Mode",
            "X-Action-Reason",
            "X-Action-Pin",
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

    async def _read_heartbeat_age(
        request: Request,
        key: str | None = None,
    ) -> tuple[float | None, bool]:
        """Read a heartbeat from Redis. Returns (age_seconds, alive).

        Uses the unified ``HEARTBEAT_MAX_AGE_SEC`` from the governance
        gate so that the API, readyz, and governance all agree on what
        constitutes a dead heartbeat.
        """
        import time as _time

        import orjson as _orjson

        from state.governance_gate import HEARTBEAT_MAX_AGE_SEC
        from state.redis_keys import HEARTBEAT_INGEST

        hb_key = key or HEARTBEAT_INGEST

        try:
            r = request.app.state.redis
            if r is None:
                return None, False
            raw = await r.get(hb_key)
            if not raw:
                return None, False
            payload = _orjson.loads(raw)
            ts = float(payload.get("ts", 0))
            if ts <= 0:
                return None, False
            age = max(0.0, _time.time() - ts)
            return round(age, 2), age <= HEARTBEAT_MAX_AGE_SEC
        except Exception:
            return None, False

    async def health(request: Request) -> dict[str, Any]:
        import math  # noqa: PLC0415

        from api.allocation_router import _feed_freshness_snapshot  # noqa: PLC0415
        from state.heartbeat_classifier import read_ingest_health  # noqa: PLC0415
        from state.redis_keys import HEARTBEAT_ENGINE  # noqa: PLC0415

        feed_snapshot = await _feed_freshness_snapshot()
        hb_age, hb_alive = await _read_heartbeat_age(request)
        engine_hb_age, engine_alive = await _read_heartbeat_age(request, key=HEARTBEAT_ENGINE)

        # Orchestrator heartbeat
        from state.redis_keys import HEARTBEAT_ORCHESTRATOR  # noqa: PLC0415

        orch_hb_age, orch_alive = await _read_heartbeat_age(request, key=HEARTBEAT_ORCHESTRATOR)

        # Read split ingest health (process vs provider)
        ingest_health_state = None
        try:
            r = request.app.state.redis
            if r is not None:
                ih = await read_ingest_health(r)
                ingest_health_state = ih.state.value
        except Exception:
            pass

        # Sanitize non-finite floats so json.dumps never emits bare
        # ``Infinity``/``NaN`` (not valid JSON; breaks dashboard parsing).
        staleness = feed_snapshot.staleness_seconds
        safe_staleness = staleness if math.isfinite(staleness) else None
        router_boot_errors = list(getattr(request.app.state, "router_boot_errors", []))

        return {
            "status": "ok",
            "service": "tuyul-fx",
            "version": "10.0.0",
            "redis_connected": feed_snapshot.state != "no_transport",
            "mt5_connected": False,
            "active_pairs": 0,
            "active_trades": 0,
            "feed_status": feed_snapshot.state,
            "freshness_class": feed_snapshot.freshness_class.value,
            "feed_staleness_seconds": safe_staleness,
            "feed_threshold_seconds": feed_snapshot.threshold_seconds,
            "feed_last_seen_ts": feed_snapshot.last_seen_ts,
            "detail": feed_snapshot.detail,
            "producer_heartbeat_age_seconds": hb_age,
            "producer_alive": hb_alive,
            "engine_heartbeat_age_seconds": engine_hb_age,
            "engine_alive": engine_alive,
            "orchestrator_heartbeat_age_seconds": orch_hb_age,
            "orchestrator_alive": orch_alive,
            "ingest_health": ingest_health_state,
            "router_boot_ok": len(router_boot_errors) == 0,
            "router_boot_errors": router_boot_errors,
        }

    app.add_api_route(
        "/health",
        health,
        methods=["GET"],
        dependencies=[Depends(verify_observability_machine_auth)],
    )

    # /healthz is the liveness probe — must be unauthenticated and
    # return instantly with NO external dependencies (no Redis, no DB).
    # Railway (and k8s) infrastructure healthchecks must always succeed
    # as long as the process is alive and accepting HTTP.
    async def healthz() -> dict[str, str]:
        return {"status": "alive", "service": "tuyul-fx"}

    app.add_api_route("/healthz", healthz, methods=["GET"])

    async def readyz(request: Request) -> JSONResponse:
        """Readiness probe — freshness-aware.

        Unlike ``/healthz`` (process liveness), this endpoint checks
        whether the system is actually *safe to serve traffic*:
        feed freshness, producer heartbeat, and warmup state.
        """
        import math as _math  # noqa: PLC0415

        from api.allocation_router import _feed_freshness_snapshot  # noqa: PLC0415
        from state.data_freshness import FreshnessClass  # noqa: PLC0415
        from state.redis_keys import HEARTBEAT_ENGINE, HEARTBEAT_ORCHESTRATOR  # noqa: PLC0415

        feed_snapshot = await _feed_freshness_snapshot()
        hb_age, hb_alive = await _read_heartbeat_age(request)
        engine_hb_age, engine_alive = await _read_heartbeat_age(request, key=HEARTBEAT_ENGINE)
        orch_hb_age, orch_alive = await _read_heartbeat_age(request, key=HEARTBEAT_ORCHESTRATOR)
        freshness_class = feed_snapshot.freshness_class

        _staleness = feed_snapshot.staleness_seconds
        checks: dict[str, Any] = {
            "feed_freshness_class": freshness_class.value,
            "feed_staleness_seconds": _staleness if _math.isfinite(_staleness) else None,
            "producer_alive": hb_alive,
            "producer_heartbeat_age_seconds": hb_age,
            "engine_alive": engine_alive,
            "engine_heartbeat_age_seconds": engine_hb_age,
            "orchestrator_alive": orch_alive,
            "orchestrator_heartbeat_age_seconds": orch_hb_age,
        }

        reasons: list[str] = []

        # Feed freshness gate — only LIVE and DEGRADED_BUT_REFRESHING
        # are legitimate for serving traffic.
        if freshness_class in (FreshnessClass.NO_PRODUCER, FreshnessClass.NO_TRANSPORT, FreshnessClass.CONFIG_ERROR):
            reasons.append(f"feed_{freshness_class.value.lower()}")
        elif freshness_class == FreshnessClass.STALE_PRESERVED:
            reasons.append("feed_stale_preserved")

        # Producer heartbeat gate
        if not hb_alive:
            reasons.append("producer_heartbeat_dead")

        # Engine heartbeat gate — analysis loop must be alive
        if not engine_alive:
            reasons.append("engine_heartbeat_dead")

        # Orchestrator heartbeat gate — compliance loop must be alive
        if not orch_alive:
            reasons.append("orchestrator_heartbeat_dead")

        ready = len(reasons) == 0
        status_code = 200 if ready else 503
        checks["ready"] = ready
        if reasons:
            checks["reasons"] = reasons

        return JSONResponse(content=checks, status_code=status_code)

    app.add_api_route(
        "/readyz",
        readyz,
        methods=["GET"],
        dependencies=[Depends(verify_observability_machine_auth)],
    )

    async def full_health(request: Request) -> dict[str, Any]:
        import math
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

        from api.allocation_router import _feed_freshness_snapshot  # noqa: PLC0415
        from state.redis_keys import HEARTBEAT_ENGINE  # noqa: PLC0415

        feed_snapshot = await _feed_freshness_snapshot()
        overall_status = "ok" if redis_ok and bool(postgres_health.get("connected")) else "degraded"
        if feed_snapshot.state in {"no_transport", "config_error"}:
            overall_status = "error"
        elif feed_snapshot.state != "fresh" and overall_status == "ok":
            overall_status = "degraded"

        hb_age, hb_alive = await _read_heartbeat_age(request)
        engine_hb_age, engine_alive = await _read_heartbeat_age(request, key=HEARTBEAT_ENGINE)

        return {
            "status": overall_status,
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
            "feed_status": feed_snapshot.state,
            "freshness_class": feed_snapshot.freshness_class.value,
            "feed_staleness_seconds": (
                feed_snapshot.staleness_seconds if math.isfinite(feed_snapshot.staleness_seconds) else None
            ),
            "feed_threshold_seconds": feed_snapshot.threshold_seconds,
            "feed_last_seen_ts": feed_snapshot.last_seen_ts,
            "feed_detail": feed_snapshot.detail,
            "producer_heartbeat_age_seconds": hb_age,
            "producer_alive": hb_alive,
            "engine_heartbeat_age_seconds": engine_hb_age,
            "engine_alive": engine_alive,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    app.add_api_route(
        "/health/full",
        full_health,
        methods=["GET"],
        dependencies=[Depends(verify_token)],
    )


# ── Factory ───────────────────────────────────────────────────────────────────


def _build_bootstrap_fallback_app(error_text: str) -> FastAPI:
    """Minimal fail-open app that keeps Railway liveness healthy during startup failures."""
    fallback = FastAPI(
        title="TUYUL FX — Bootstrap Fallback",
        version="10.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @fallback.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "alive", "service": "tuyul-fx", "degraded": True}

    @fallback.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "degraded",
            "service": "tuyul-fx",
            "router_boot_ok": False,
            "router_boot_errors": [error_text],
        }

    return fallback


def _create_app_inner() -> FastAPI:
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

    # Middleware stack — order matters!
    # FastAPI/Starlette executes middleware in REVERSE add-order (last-added = outermost).
    # CORS must be outermost so preflight OPTIONS responses always carry
    # Access-Control-Allow-* headers, even when an inner middleware (rate-limit)
    # short-circuits.
    _add_security_middleware(app, force_https)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RateLimitMiddleware)
    _add_cors(app)  # outermost — handles preflight before anything else

    # Health endpoints first so infra liveness stays available even if
    # downstream router imports fail during bootstrap.
    _register_health_routes(app)

    router_boot_errors: list[str] = []

    # Mount all routers from the registry. In degraded fail-open mode,
    # keep process alive with health endpoints so orchestrators can
    # inspect diagnostics instead of seeing a dead container.
    fail_open = _env_bool("ROUTER_BOOT_FAIL_OPEN", default=True)
    try:
        for router, description in load_routers():
            app.include_router(router)
            logger.debug("Mounted router: %s", description)

        # Guard: fail fast if any (method, path) was registered more than once.
        _assert_no_duplicate_routes(app)
    except Exception as exc:
        detail = f"router_bootstrap_failed: {exc!s}"
        router_boot_errors.append(detail)
        logger.exception("Router bootstrap failed")
        if not fail_open:
            raise

    app.state.router_boot_errors = router_boot_errors

    # Dev routes (gated)
    if enable_dev_routes:
        _register_dev_routes(app)

    return app


def create_app() -> FastAPI:
    """Build the FastAPI application with fail-open bootstrap protection.

    If ``API_BOOT_FAIL_OPEN`` is truthy (default) and the inner factory
    raises, returns a minimal fallback app that keeps ``/healthz`` alive
    so operators can diagnose the failure via ``/health``.
    """
    fail_open = _env_bool("API_BOOT_FAIL_OPEN", True)
    try:
        return _create_app_inner()
    except Exception as exc:
        if not fail_open:
            raise
        logger.exception("API bootstrap failed — enabling fallback liveness app")
        return _build_bootstrap_fallback_app(f"api_bootstrap_failed: {exc!s}")
