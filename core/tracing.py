"""
OpenTelemetry tracing helper for Wolf-15 Layer System.

Provides a single, lazily-initialised tracer that instruments per-layer
pipeline execution with OTEL spans.  When no OTEL SDK is configured the
tracer degrades gracefully to a no-op provider — no external dependency
is required at runtime unless an exporter is explicitly configured.

Usage::

    from core.tracing import get_tracer, layer_span

    with layer_span("L1", symbol="EURUSD") as span:
        result = do_l1_work()
        span.set_attribute("layer.result_keys", list(result.keys()))

Environment variables (optional):

    OTEL_SERVICE_NAME   — service name reported to the backend
                          (default: wolf15-pipeline)
    OTEL_EXPORTER_OTLP_ENDPOINT — OTLP gRPC/HTTP endpoint, e.g.
                          http://localhost:4317
                          When unset no exporter is attached and spans
                          are discarded after measurement (no-op export).

Zone: core (infrastructure/observability only — no execution side-effects).
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    _has_otel = True
except ImportError:  # pragma: no cover
    from opentelemetry import trace

    Resource: Any = None
    TracerProvider: Any = None
    BatchSpanProcessor: Any = None
    ConsoleSpanExporter: Any = None
    _has_otel = False

if TYPE_CHECKING:
    from opentelemetry.trace import Span

_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "wolf15-pipeline")
_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

_tracer: trace.Tracer | None = None


def _build_provider() -> trace.TracerProvider:
    """Construct and configure the TracerProvider.

    If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set an OTLP exporter is wired up;
    otherwise a ``ConsoleSpanExporter`` is attached only when
    ``OTEL_SDK_CONSOLE`` env var equals ``"1"`` — otherwise no exporter is
    attached and spans are produced but silently dropped (no stdout noise in
    tests/CI).
    """
    if not _has_otel:
        return trace.NoOpTracerProvider()

    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    if _OTLP_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
                OTLPSpanExporter,
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=_OTLP_ENDPOINT))
            )
        except ImportError:
            # opentelemetry-exporter-otlp not installed — fall through to
            # console or no-op
            pass

    if os.getenv("OTEL_SDK_CONSOLE") == "1":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    return provider


def get_tracer() -> trace.Tracer:
    """Return the global Wolf-15 tracer (initialised once, then cached)."""
    global _tracer  # noqa: PLW0603
    if _tracer is None:
        if _has_otel:
            # Only set provider if none has been registered yet (another
            # module such as infrastructure.tracing may have already done so).
            existing = trace.get_tracer_provider()
            _is_proxy = type(existing).__name__ == "ProxyTracerProvider"
            if _is_proxy:
                provider = _build_provider()
                trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer(__name__, schema_url="")
        else:
            # Minimal stub so callers never deal with None
            _tracer = _NoOpTracer()  # type: ignore[assignment]
    return _tracer  # type: ignore[return-value]


@contextmanager
def layer_span(
    layer_name: str,
    symbol: str = "",
    **extra_attributes: str | int | float | bool,
) -> Generator[Span, None, None]:
    """Context manager that wraps a layer call in an OTEL span.

    Span attributes set automatically:
        layer.name  — e.g. "L1", "L2", …, "L12"
        layer.symbol — trading pair, e.g. "EURUSD"
        <extra_attributes> — any additional k/v pairs passed by caller

    On exception the span is marked with an ERROR status and the exception is
    recorded before being re-raised, preserving the existing pipeline
    error-handling contract.

    This helper is pure observability and has no effect on Layer-12 verdict
    authority.
    """
    tracer = get_tracer()
    if _has_otel:
        with tracer.start_as_current_span(f"wolf.layer.{layer_name}") as span:
            span.set_attribute("layer.name", layer_name)
            if symbol:
                span.set_attribute("layer.symbol", symbol)
            for k, v in extra_attributes.items():
                span.set_attribute(k, v)
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(
                    trace.StatusCode.ERROR,
                    description=str(exc),
                )
                raise
    else:
        yield _NullSpan()  # type: ignore[misc]


# ── Minimal stubs used when opentelemetry is absent ─────────────────

class _NullSpan:
    """Stub span used when opentelemetry is not installed."""

    def set_attribute(self, _key: str, _value: object) -> None:
        pass

    def record_exception(self, _exc: BaseException) -> None:
        pass

    def set_status(self, *_args: object, **_kwargs: object) -> None:
        pass


class _NoOpTracer:
    """Stub tracer used when opentelemetry is not installed."""

    def start_as_current_span(self, _name: str, **_kwargs: object) -> contextlib.AbstractContextManager[_NullSpan]:  # noqa: E501
        return contextlib.nullcontext(_NullSpan())
