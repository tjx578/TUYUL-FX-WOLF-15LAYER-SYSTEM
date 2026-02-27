"""
Prometheus HTTP instrumentation middleware.

Records per-request metrics into the Wolf-15 MetricsRegistry:

    wolf_http_requests_total{method, path_template, status_code}  — counter
    wolf_http_request_duration_seconds{method, path_template}      — histogram

Path templates collapse parametric segments (e.g. ``/api/v1/trades/42`` →
``/api/v1/trades/{id}``) by leveraging Starlette's matched route so cardinality
remains bounded.  The ``/metrics`` scrape endpoint itself is excluded from
instrumentation to avoid feedback loops.

Environment variables:
    PROMETHEUS_MIDDLEWARE_ENABLED   — "true" / "false" (default "true")
"""

from __future__ import annotations

import os
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match
from starlette.types import ASGIApp

from core.metrics import Counter, Histogram, get_registry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


MIDDLEWARE_ENABLED: bool = _env_bool("PROMETHEUS_MIDDLEWARE_ENABLED", True)

# Paths that should not be instrumented (avoids self-referential loop)
_SKIP_PATHS: frozenset[str] = frozenset({"/metrics", "/health", "/favicon.ico"})

# ---------------------------------------------------------------------------
# Register metrics once against the shared registry
# ---------------------------------------------------------------------------

_R = get_registry()

HTTP_REQUESTS_TOTAL: Counter = _R.counter(
    "wolf_http_requests_total",
    "Total HTTP requests by method, path template and status code",
    label_names=("method", "path_template", "status_code"),
)

HTTP_REQUEST_DURATION: Histogram = _R.histogram(
    "wolf_http_request_duration_seconds",
    "HTTP request duration in seconds by method and path template",
    label_names=("method", "path_template"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _get_path_template(request: Request) -> str:
    """Return the matched route path (with ``{param}`` placeholders) or raw path."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that instruments HTTP requests for Prometheus."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not MIDDLEWARE_ENABLED or request.url.path in _SKIP_PATHS:
            return await call_next(request)

        method = request.method.upper()
        path_template = _get_path_template(request)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        status_code = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            path_template=path_template,
            status_code=status_code,
        ).inc()

        HTTP_REQUEST_DURATION.labels(
            method=method,
            path_template=path_template,
        ).observe(duration)

        return response
