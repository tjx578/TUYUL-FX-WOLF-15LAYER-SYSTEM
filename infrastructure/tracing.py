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
    from opentelemetry.context import Context
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import extract, inject
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _HAS_OTEL = True
except Exception:  # pragma: no cover - graceful degradation when OTEL deps missing
    from opentelemetry import trace  # type: ignore

    Context = Any  # type: ignore[misc,assignment]
    _HAS_OTEL = False


_PROVIDER_INITIALIZED = False
_TRACER_CACHE: dict[str, trace.Tracer] = {}
_FASTAPI_INSTRUMENTED = False
_REDIS_INSTRUMENTED = False
_ASYNCIO_INSTRUMENTED = False
_REQUESTS_INSTRUMENTED = False
_HTTPX_INSTRUMENTED = False

TRACE_CONTEXT_FIELDS: tuple[str, ...] = ("traceparent", "tracestate", "baggage")


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _tracing_enabled() -> bool:
    return _as_bool(os.getenv("OTEL_ENABLED"), default=True)


def _init_provider_once(service_name: str) -> None:
    global _PROVIDER_INITIALIZED  # noqa: PLW0603
    if _PROVIDER_INITIALIZED or not _HAS_OTEL or not _tracing_enabled():
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4317")
    insecure = _as_bool(os.getenv("OTEL_EXPORTER_OTLP_INSECURE"), default=True)
    service_version = os.getenv("OTEL_SERVICE_VERSION", "unknown")
    deployment_environment = os.getenv("OTEL_DEPLOYMENT_ENV", os.getenv("APP_ENV", "unknown"))

    try:
        resource = Resource(attributes={
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": deployment_environment,
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _PROVIDER_INITIALIZED = True
        logger.info(
            "Tracing enabled service={} endpoint={} env={}",
            service_name,
            endpoint,
            deployment_environment,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Tracing init failed service={} err={}", service_name, exc)


def setup_tracer(service_name: str) -> trace.Tracer:
    """Initialise provider (once) and return a named tracer."""
    _init_provider_once(service_name)
    cached = _TRACER_CACHE.get(service_name)
    if cached is not None:
        return cached
    tracer = trace.get_tracer(service_name)
    _TRACER_CACHE[service_name] = tracer
    return tracer


def instrument_fastapi(app: Any) -> None:
    """Auto-instrument FastAPI app if instrumentation package is installed."""
    global _FASTAPI_INSTRUMENTED  # noqa: PLW0603
    if _FASTAPI_INSTRUMENTED or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _FASTAPI_INSTRUMENTED = True
    except Exception:
        return


def instrument_redis() -> None:
    """Auto-instrument redis client calls if package is installed."""
    global _REDIS_INSTRUMENTED  # noqa: PLW0603
    if _REDIS_INSTRUMENTED or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        _REDIS_INSTRUMENTED = True
    except Exception:
        return


def instrument_asyncio() -> None:
    """Auto-instrument asyncio scheduling if package is installed."""
    global _ASYNCIO_INSTRUMENTED  # noqa: PLW0603
    if _ASYNCIO_INSTRUMENTED or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor

        AsyncioInstrumentor().instrument()
        _ASYNCIO_INSTRUMENTED = True
    except Exception:
        return


def instrument_requests() -> None:
    """Auto-instrument requests client calls if package is installed."""
    global _REQUESTS_INSTRUMENTED  # noqa: PLW0603
    if _REQUESTS_INSTRUMENTED or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
        _REQUESTS_INSTRUMENTED = True
    except Exception:
        return


def instrument_httpx() -> None:
    """Auto-instrument httpx client calls if package is installed."""
    global _HTTPX_INSTRUMENTED  # noqa: PLW0603
    if _HTTPX_INSTRUMENTED or not _tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        _HTTPX_INSTRUMENTED = True
    except Exception:
        return


def inject_trace_context(carrier: MutableMapping[str, Any]) -> None:
    """Inject current trace context into a mutable payload carrier."""
    if not _HAS_OTEL:
        return
    inject(carrier=carrier)


def extract_trace_context(carrier: Mapping[str, Any]) -> Context | None:
    """Extract trace context from a payload carrier."""
    if not _HAS_OTEL:
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
