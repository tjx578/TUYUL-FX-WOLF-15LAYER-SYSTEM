"""Shared OpenTelemetry tracing setup + propagation helpers.

Zone: infrastructure (observability only, no decision authority).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from typing import Any

from loguru import logger

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import extract, inject
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _has_otel = True
except Exception:  # pragma: no cover - graceful degradation when OTEL deps missing
    from opentelemetry import trace

    Resource: Any = None
    TracerProvider: Any = None
    OTLPSpanExporter: Any = None
    BatchSpanProcessor: Any = None
    extract: Any = None
    inject: Any = None
    _has_otel = False


_provider_initialized = False
_tracer_cache: dict[str, trace.Tracer] = {}
_fastapi_instrumented = False
_redis_instrumented = False
_asyncio_instrumented = False
_requests_instrumented = False
_httpx_instrumented = False

TRACE_CONTEXT_FIELDS: tuple[str, ...] = ("traceparent", "tracestate", "baggage")


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _tracing_enabled() -> bool:
    """Return True only when tracing is explicitly enabled AND an endpoint is configured.

    Without an OTLP endpoint, initializing a TracerProvider and instrumenting
    libraries adds CPU/memory overhead with zero observability benefit.
    """
    enabled = _as_bool(os.getenv("OTEL_ENABLED"), default=False)
    if not enabled:
        return False
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return bool(endpoint)


def _init_provider_once(service_name: str) -> None:
    global _provider_initialized  # noqa: PLW0603
    if _provider_initialized or not _has_otel or not _tracing_enabled():
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    insecure = _as_bool(os.getenv("OTEL_EXPORTER_OTLP_INSECURE"), default=True)
    service_version = os.getenv("OTEL_SERVICE_VERSION", "unknown")
    deployment_environment = os.getenv("OTEL_DEPLOYMENT_ENV", os.getenv("APP_ENV", "unknown"))

    if not endpoint:
        # _tracing_enabled() should have caught this, but guard defensively.
        _provider_initialized = True
        logger.info(
            "Tracing disabled service={} reason=no_endpoint env={}",
            service_name,
            deployment_environment,
        )
        return

    try:
        resource = Resource(
            attributes={
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment": deployment_environment,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        # Only set if no real provider has been registered yet.
        existing = trace.get_tracer_provider()
        _is_proxy = type(existing).__name__ == "ProxyTracerProvider"
        if _is_proxy:
            trace.set_tracer_provider(provider)
        _provider_initialized = True
        logger.info(
            "Tracing enabled service={} endpoint={} env={}",
            service_name,
            endpoint,
            deployment_environment,
        )
    except Exception as exc:  # pragma: no cover
        _provider_initialized = True
        logger.warning("Tracing init failed service={} err={}", service_name, exc)


def setup_tracer(service_name: str) -> trace.Tracer:
    """Initialise provider (once) and return a named tracer."""
    _init_provider_once(service_name)
    cached = _tracer_cache.get(service_name)
    if cached is not None:
        return cached
    tracer = trace.get_tracer(service_name)
    _tracer_cache[service_name] = tracer
    return tracer


def instrument_fastapi(app: Any) -> None:
    """Auto-instrument FastAPI app if instrumentation package is installed."""
    global _fastapi_instrumented  # noqa: PLW0603
    if _fastapi_instrumented or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _fastapi_instrumented = True
    except Exception:
        return


def instrument_redis() -> None:
    """Auto-instrument redis client calls if package is installed."""
    global _redis_instrumented  # noqa: PLW0603
    if _redis_instrumented or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        _redis_instrumented = True
    except Exception:
        return


def instrument_asyncio() -> None:
    """Auto-instrument asyncio scheduling if package is installed."""
    global _asyncio_instrumented  # noqa: PLW0603
    if _asyncio_instrumented or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor

        AsyncioInstrumentor().instrument()
        _asyncio_instrumented = True
    except Exception:
        return


def instrument_requests() -> None:
    """Auto-instrument requests client calls if package is installed."""
    global _requests_instrumented  # noqa: PLW0603
    if _requests_instrumented or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
        _requests_instrumented = True
    except Exception:
        return


def instrument_httpx() -> None:
    """Auto-instrument httpx client calls if package is installed."""
    global _httpx_instrumented  # noqa: PLW0603
    if _httpx_instrumented or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
    except Exception:
        return


def inject_trace_context(carrier: MutableMapping[str, Any]) -> None:
    """Inject current trace context into a mutable payload carrier."""
    if not _has_otel:
        return
    inject(carrier=carrier)


def extract_trace_context(carrier: Mapping[str, Any]) -> Any | None:
    """Extract trace context from a payload carrier."""
    if not _has_otel:
        return None
    return extract(carrier=carrier)


def extract_trace_carrier(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return only trace propagation fields from a Redis/message payload."""
    carrier: dict[str, str] = {}
    for field in TRACE_CONTEXT_FIELDS:
        raw = payload.get(field)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            carrier[field] = value
    return carrier
