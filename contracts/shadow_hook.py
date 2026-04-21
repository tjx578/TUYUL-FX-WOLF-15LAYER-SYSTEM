"""P1 live wiring — feature-flagged shadow capture entrypoint.

The pipeline integrates shadow capture via exactly two calls:

  1. :func:`begin_shadow_session` immediately after it has ``symbol``
     and a stable per-run ``signal_id``. Returns ``None`` when the
     flag is off → pipeline pays zero cost.
  2. :func:`finalize_shadow_session` at the end of ``execute()``.
     Safe no-op on ``None``.

Between those, the pipeline opts into capture at each layer seam::

    session and session.ingest_chain_result(phase1_result)
    session and session.capture(l4_out, layer_id="L4")
    # …

Feature flag: ``WOLF_SHADOW_CAPTURE_ENABLED`` (truthy values: ``"1"``,
``"true"``, ``"TRUE"``). Default: **off**. Override with
``WOLF_SHADOW_JOURNAL_PATH`` to point at a custom journal file.

Safety contract:
  - Flag off → helpers return ``None`` / no-op, pipeline untouched.
  - Flag on + any error → logged at DEBUG, never raised.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from contracts.shadow_capture import ShadowCaptureSession
from contracts.shadow_sink import ShadowJournalSink

logger = logging.getLogger(__name__)

# Best-effort metrics. Any import/attribute failure here MUST NOT break
# the hook — metrics are advisory for ops dashboards only.
try:
    from core.metrics import (
        SHADOW_CAPTURE_ENVELOPES_TOTAL,
        SHADOW_CAPTURE_FAILURES_TOTAL,
        SHADOW_CAPTURE_WRITES_TOTAL,
    )

    _METRICS_OK = True
except Exception:  # noqa: BLE001
    SHADOW_CAPTURE_ENVELOPES_TOTAL = None  # type: ignore[assignment]
    SHADOW_CAPTURE_FAILURES_TOTAL = None  # type: ignore[assignment]
    SHADOW_CAPTURE_WRITES_TOTAL = None  # type: ignore[assignment]
    _METRICS_OK = False


def _safe_inc(counter: Any, **labels: str) -> None:
    if counter is None:
        return
    try:
        counter.labels(**labels).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("shadow metrics inc failed: %s", exc)


_FLAG_ENV = "WOLF_SHADOW_CAPTURE_ENABLED"
_TRUTHY = frozenset({"1", "true", "TRUE", "True", "yes", "on"})


def is_enabled() -> bool:
    """Check the feature flag. Pure, re-read every call."""
    return os.getenv(_FLAG_ENV, "0") in _TRUTHY


def begin_shadow_session(
    *,
    symbol: str,
    signal_id: str | None = None,
    timeframe: str = "H1",
    runtime_context_ref: str | None = None,
) -> ShadowCaptureSession | None:
    """Return a new :class:`ShadowCaptureSession` if the flag is on.

    Returns ``None`` when the flag is off — the pipeline then checks
    ``if session is not None`` (or ``session and session.capture(...)``)
    at each call-site, which is a single short-circuit expression.

    Any exception during session construction (e.g. upstream coercion
    bug) is caught and logged, returning ``None`` — the pipeline remains
    unaffected.
    """
    if not is_enabled():
        return None
    try:
        sid = signal_id or f"shadow-{uuid.uuid4().hex[:16]}"
        ctx = runtime_context_ref or f"runtime:{symbol}:{sid}"
        return ShadowCaptureSession(
            signal_id=sid,
            symbol=symbol,
            timeframe=timeframe,
            runtime_context_ref=ctx,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("begin_shadow_session failed: %s", exc)
        return None


# Module-level lazy sink so pipeline callers don't have to manage it.
_SINK: ShadowJournalSink | None = None


def _get_sink() -> ShadowJournalSink:
    global _SINK
    if _SINK is None:
        _SINK = ShadowJournalSink()
    return _SINK


def set_sink(sink: ShadowJournalSink | None) -> None:
    """Override the module-level sink (tests use this)."""
    global _SINK
    _SINK = sink


def finalize_shadow_session(
    session: ShadowCaptureSession | None,
) -> dict[str, Any] | None:
    """Build the shadow bundle and write it to the journal sink.

    Accepts ``None`` (flag-off path) and returns ``None`` — this is the
    common case and must stay cheap. Returns the summary dict on
    successful record, or ``None`` on failure. **Never raises.**
    """
    if session is None:
        return None
    try:
        bundle, _diag = session.try_build()
        summary = session.summary()
        ok = _get_sink().record(summary, bundle)
        _safe_inc(SHADOW_CAPTURE_WRITES_TOTAL, outcome="ok" if ok else "error")
        _safe_inc(
            SHADOW_CAPTURE_ENVELOPES_TOTAL,
            symbol=str(summary.get("symbol", "UNKNOWN")),
        )
        fc = int(summary.get("failure_count", 0) or 0)
        if fc > 0 and SHADOW_CAPTURE_FAILURES_TOTAL is not None:
            try:
                SHADOW_CAPTURE_FAILURES_TOTAL.labels(symbol=str(summary.get("symbol", "UNKNOWN"))).inc(fc)
            except Exception as exc:  # noqa: BLE001
                logger.debug("shadow failure counter inc failed: %s", exc)
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.debug("finalize_shadow_session failed: %s", exc)
        return None


__all__ = [
    "begin_shadow_session",
    "finalize_shadow_session",
    "is_enabled",
    "set_sink",
]
