"""P1-A Runtime Dual Emit Adapter.

Infrastructure for running legacy layer outputs and Blueprint v2 envelopes
*in parallel* without touching any existing layer or pipeline code. The
legacy dict/dataclass result continues to flow through the existing
``WolfContext`` / ``verdict_engine`` path; this module lets the runtime
additionally record a frozen :class:`LayerEnvelope` per layer for audit,
replay, and shadow-``DecisionBundle`` construction.

Hard safety contract:
  - **Projection errors never raise into the legacy path.** If an envelope
    cannot be built (e.g., validator rejects account-state leak, or a layer
    emitted an unknown status), the collector records a ``ProjectionFailure``
    entry and the pipeline keeps running on legacy output. The dual-emit
    mode must not be capable of breaking a live trade.
  - **Immutable storage.** Envelopes are ``frozen`` Pydantic models; the
    collector only appends, never rewrites. Replay integrity is preserved.
  - **No execution authority.** This module produces evidence only. It does
    not decide, veto, size, or route.
  - **No account state.** The envelope validator rejects balance/equity/
    margin recursively; that invariant is inherited here.

Zone: contracts — validation & audit infrastructure.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from contracts.adapters import layer_dict_to_envelope
from contracts.layer_envelope import Direction, EvidencePlane, LayerEnvelope

# ─────────────────────────────────────────────────────────────────────────
# Failure record (projection errors recorded, never raised into legacy)
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectionFailure:
    """Captured projection error. Immutable audit trail entry."""

    layer_id: str
    error_type: str
    error_message: str
    recorded_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


# ─────────────────────────────────────────────────────────────────────────
# EnvelopeCollection — per-signal envelope store
# ─────────────────────────────────────────────────────────────────────────


class EnvelopeCollection:
    """Thread-safe store of envelopes + projection failures for one signal.

    Designed as the shadow audit trail for Blueprint v2 runtime. A single
    instance corresponds to one ``signal_id`` / pipeline run. Methods are
    read-mostly after the pipeline finishes; concurrent append is guarded
    by an internal lock so parallel phases (enrichment, validation) can
    register their envelopes safely.
    """

    def __init__(self, signal_id: str, symbol: str) -> None:
        if not signal_id or not signal_id.strip():
            raise ValueError("signal_id must be a non-empty string")
        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        self._signal_id = signal_id
        self._symbol = symbol
        self._lock = threading.Lock()
        self._envelopes: dict[str, LayerEnvelope] = {}
        self._failures: list[ProjectionFailure] = []
        self._created_at = datetime.now(tz=UTC)

    # ── identity ──────────────────────────────────────────────────────
    @property
    def signal_id(self) -> str:
        return self._signal_id

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def created_at(self) -> datetime:
        return self._created_at

    # ── mutation (append-only) ────────────────────────────────────────
    def add(self, envelope: LayerEnvelope) -> None:
        """Register an envelope. Rejects mismatched signal_id / duplicate layer."""
        if envelope.signal_id != self._signal_id:
            raise ValueError(f"envelope.signal_id={envelope.signal_id!r} != collection {self._signal_id!r}")
        with self._lock:
            if envelope.layer_id in self._envelopes:
                raise ValueError(
                    f"envelope for layer {envelope.layer_id!r} already recorded; collection is append-only"
                )
            self._envelopes[envelope.layer_id] = envelope

    def record_failure(self, failure: ProjectionFailure) -> None:
        """Append a projection failure. Never raises."""
        with self._lock:
            self._failures.append(failure)

    # ── query ─────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._envelopes)

    def __contains__(self, layer_id: str) -> bool:
        return layer_id in self._envelopes

    def get(self, layer_id: str) -> LayerEnvelope | None:
        return self._envelopes.get(layer_id)

    def all_envelopes(self) -> list[LayerEnvelope]:
        """Return envelopes in insertion order (Python dict preserves this)."""
        with self._lock:
            return list(self._envelopes.values())

    def by_plane(self, plane: EvidencePlane) -> list[LayerEnvelope]:
        return [env for env in self._envelopes.values() if env.plane == plane]

    def failures(self) -> list[ProjectionFailure]:
        with self._lock:
            return list(self._failures)

    def hard_blockers(self) -> list[str]:
        """Aggregate blockers from non-meta, non-post-authority planes.

        Mirrors :meth:`DecisionBundle.hard_blockers` semantics so callers can
        pre-check a shadow bundle without constructing it. Meta plane
        (L13/L15) is advisory, and post_authority_veto (V11) runs *after*
        L12 and therefore is not a pre-verdict hard blocker.
        """
        excluded: set[EvidencePlane] = {"meta", "post_authority_veto"}
        out: list[str] = []
        seen: set[str] = set()
        for env in self._envelopes.values():
            if env.plane in excluded:
                continue
            if not env.is_blocking():
                continue
            for code in env.blockers:
                if code not in seen:
                    seen.add(code)
                    out.append(code)
        return out

    def summary(self) -> dict[str, Any]:
        """Compact dict for journaling / audit logs."""
        with self._lock:
            planes: dict[str, int] = {}
            for env in self._envelopes.values():
                planes[env.plane] = planes.get(env.plane, 0) + 1
            return {
                "signal_id": self._signal_id,
                "symbol": self._symbol,
                "created_at": self._created_at.isoformat(),
                "envelope_count": len(self._envelopes),
                "failure_count": len(self._failures),
                "planes": planes,
                "layers": list(self._envelopes.keys()),
                "hard_blockers": self.hard_blockers(),
            }


# ─────────────────────────────────────────────────────────────────────────
# Dual-emit helper — the single call-site hook
# ─────────────────────────────────────────────────────────────────────────


def dual_emit(
    legacy_result: Mapping[str, Any] | Any,
    collection: EnvelopeCollection,
    *,
    layer_id: str | None = None,
    plane: EvidencePlane | None = None,
    module: str | None = None,
    stale_after_ms: int | None = None,
    direction: Direction | None = None,
    confidence: float | None = None,
) -> LayerEnvelope | None:
    """Project a legacy layer result into an envelope and record it.

    This is the **only** hook the runtime needs to insert after a layer
    finishes. The legacy ``legacy_result`` is returned untouched by the
    caller's existing pipeline; the envelope is recorded as shadow audit.

    Returns the envelope on success, or ``None`` on projection failure
    (failures are captured in the collection, never raised). This is the
    core of the dual-emit safety contract: **the legacy path never sees an
    exception from envelope projection**.

    Parameters mirror :func:`layer_dict_to_envelope`; they only exist to
    override adapter defaults when a layer reports non-canonical shapes.
    """
    try:
        envelope = layer_dict_to_envelope(
            legacy_result,
            signal_id=collection.signal_id,
            symbol=collection.symbol,
            layer_id=layer_id,
            plane=plane,
            module=module,
            stale_after_ms=stale_after_ms,
            direction=direction,
            confidence=confidence,
        )
        collection.add(envelope)
        return envelope
    except Exception as exc:  # noqa: BLE001 — deliberate isolation boundary
        resolved_layer = layer_id
        if resolved_layer is None:
            if isinstance(legacy_result, Mapping):
                resolved_layer = str(legacy_result.get("layer") or "UNKNOWN")
            else:
                resolved_layer = "UNKNOWN"
        collection.record_failure(
            ProjectionFailure(
                layer_id=resolved_layer,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        )
        return None


__all__ = [
    "EnvelopeCollection",
    "ProjectionFailure",
    "dual_emit",
]
