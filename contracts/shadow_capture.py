"""P1-A.5 Shadow Capture Session — opt-in runtime wiring.

Provides a per-signal capture context that orchestrates :func:`dual_emit`
and :func:`try_build_shadow_bundle` into a single, caller-friendly object.
This is the landing zone for wiring runtime call-sites *without* modifying
any existing layer, chain adapter, or verdict engine.

Usage (pipeline-side, opt-in)::

    from contracts.shadow_capture import ShadowCaptureSession

    session = ShadowCaptureSession(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="H1",
        runtime_context_ref=f"stream:runtime:{symbol}:{seq}",
    )

    chain_result = phase1_adapter.execute(symbol)
    session.ingest_chain_result(chain_result)          # captures L1, L2, L3

    # Phase 2+ layers (L4..L11) — call-site passes legacy dict / governor output.
    session.capture(l4_out)
    session.capture(l5_out)
    # ...

    bundle, diag = session.try_build()                 # shadow only, no L12 swap
    journal.record_shadow(session.summary(), bundle)   # audit only

Safety contract (same as dual_emit):
  - **No exception from shadow capture ever reaches the legacy path.**
  - **No authority drift.** Session never decides a verdict; it only
    collects evidence envelopes for a *shadow* ``DecisionBundle``.
  - **Append-only** store underneath; replay integrity preserved.

Zone: contracts — runtime infrastructure, validation/audit only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from contracts.decision_bundle import DecisionBundle
from contracts.decision_bundle_builder import try_build_shadow_bundle
from contracts.layer_envelope import Direction, EvidencePlane, LayerEnvelope
from contracts.runtime_projection import (
    EnvelopeCollection,
    ProjectionFailure,
    dual_emit,
)


class ShadowCaptureSession:
    """One shadow capture session per signal / pipeline run.

    Thin orchestrator around :class:`EnvelopeCollection` with:
      - a single ``capture()`` entry point for per-layer legacy output;
      - a ``ingest_chain_result()`` helper for ``Phase1ChainAdapter`` output;
      - a ``try_build()`` convenience that returns a shadow
        :class:`DecisionBundle` + diagnostics (never raises).

    The session MUST NOT be reused across signals. ``signal_id`` and
    ``symbol`` are bound at construction time and validated by
    :class:`EnvelopeCollection`.
    """

    def __init__(
        self,
        *,
        signal_id: str,
        symbol: str,
        timeframe: str,
        runtime_context_ref: str,
    ) -> None:
        if not timeframe or not timeframe.strip():
            raise ValueError("timeframe must be a non-empty string")
        if not runtime_context_ref or not runtime_context_ref.strip():
            raise ValueError("runtime_context_ref must be a non-empty string")
        self._collection = EnvelopeCollection(signal_id=signal_id, symbol=symbol)
        self._timeframe = timeframe
        self._runtime_context_ref = runtime_context_ref
        self._build_diagnostics: list[dict[str, Any]] = []

    # ── identity / read-only views ─────────────────────────────────────
    @property
    def signal_id(self) -> str:
        return self._collection.signal_id

    @property
    def symbol(self) -> str:
        return self._collection.symbol

    @property
    def timeframe(self) -> str:
        return self._timeframe

    @property
    def runtime_context_ref(self) -> str:
        return self._runtime_context_ref

    @property
    def collection(self) -> EnvelopeCollection:
        """Expose the underlying collection (read-only use)."""
        return self._collection

    # ── capture ───────────────────────────────────────────────────────
    def capture(
        self,
        legacy_result: Mapping[str, Any] | Any,
        *,
        layer_id: str | None = None,
        plane: EvidencePlane | None = None,
        module: str | None = None,
        direction: Direction | None = None,
        confidence: float | None = None,
        stale_after_ms: int | None = None,
    ) -> LayerEnvelope | None:
        """Capture one layer's legacy output as a shadow envelope.

        Thin pass-through to :func:`dual_emit`. Returns the projected
        envelope on success or ``None`` on projection failure (failure is
        recorded on the underlying collection; the caller is never
        impacted).
        """
        return dual_emit(
            legacy_result,
            self._collection,
            layer_id=layer_id,
            plane=plane,
            module=module,
            direction=direction,
            confidence=confidence,
            stale_after_ms=stale_after_ms,
        )

    def capture_many(
        self,
        results: Iterable[tuple[str, Mapping[str, Any] | Any]],
    ) -> list[LayerEnvelope | None]:
        """Capture multiple ``(layer_id, legacy_result)`` pairs.

        ``layer_id`` is passed explicitly so callers can drive plane
        selection even when a legacy dict is missing its ``layer`` field
        (e.g. enrichment engines that return their own shape).
        """
        return [self.capture(res, layer_id=lid) for lid, res in results]

    def ingest_chain_result(self, chain_result: Any) -> None:
        """Ingest a ``ChainResult``-shaped object (has ``.l1``, ``.l2``, ``.l3``).

        Also accepts a plain dict with ``"l1"``/``"l2"``/``"l3"`` keys so
        this helper works against ``ChainResult.to_dict()`` output too.

        Missing or empty layer dicts are skipped silently — they indicate
        the chain never reached that layer, which is an upstream signal
        that L12 handles via the legacy path; the shadow session should
        not fabricate envelopes for layers that did not run.
        """
        for layer_id in ("L1", "L2", "L3"):
            key = layer_id.lower()
            layer_dict = self._extract_layer(chain_result, key)
            if not layer_dict:
                continue
            self.capture(layer_dict, layer_id=layer_id)

    @staticmethod
    def _extract_layer(chain_result: Any, key: str) -> Mapping[str, Any] | None:
        if chain_result is None:
            return None
        if isinstance(chain_result, Mapping):
            val = chain_result.get(key)
        else:
            val = getattr(chain_result, key, None)
        return val if isinstance(val, Mapping) and val else None

    # ── introspection ─────────────────────────────────────────────────
    def envelopes(self) -> list[LayerEnvelope]:
        return self._collection.all_envelopes()

    def failures(self) -> list[ProjectionFailure]:
        return self._collection.failures()

    def hard_blockers(self) -> list[str]:
        return self._collection.hard_blockers()

    def summary(self) -> dict[str, Any]:
        base = self._collection.summary()
        base["timeframe"] = self._timeframe
        base["runtime_context_ref"] = self._runtime_context_ref
        base["build_diagnostics"] = list(self._build_diagnostics)
        return base

    # ── build ─────────────────────────────────────────────────────────
    def try_build(
        self,
        *,
        created_at: datetime | None = None,
    ) -> tuple[DecisionBundle | None, dict[str, Any] | None]:
        """Build a shadow :class:`DecisionBundle`. Never raises.

        Each failure is appended to the session's build diagnostics so
        operators can audit why shadow mode didn't produce a bundle on a
        particular run.
        """
        bundle, diag = try_build_shadow_bundle(
            self._collection,
            timeframe=self._timeframe,
            runtime_context_ref=self._runtime_context_ref,
            created_at=created_at or datetime.now(tz=UTC),
        )
        if diag is not None:
            self._build_diagnostics.append(diag)
        return bundle, diag


__all__ = ["ShadowCaptureSession"]
