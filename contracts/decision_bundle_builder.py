"""P1-B Shadow DecisionBundle Builder.

Pure projection from :class:`EnvelopeCollection` → :class:`DecisionBundle`.

Purpose
-------
Builds a **shadow** ``DecisionBundle`` from the envelopes collected during
a dual-emit run. In P1-B this bundle is *not* consumed by the live L12
path; it exists for audit, replay preparation, and parity testing. Once
shadow parity is proven (P1-C) the same bundle can be promoted to be the
authoritative L12 input.

Authority invariants preserved here:
  - Envelopes with ``plane == "post_authority_veto"`` (V11) are silently
    excluded from the bundle. Per constitutional doctrine, V11 runs AFTER
    L12 emits EXECUTE. Excluding it from the pre-L12 bundle is required
    by ``DecisionBundle._reject_post_authority_plane``.
  - No authority promotion: the builder never converts advisory direction
    in an envelope into a BUY/SELL verdict. That is L12's sole authority.
  - No account state: the account-state rejection is enforced upstream at
    the ``LayerEnvelope`` validator and carries through here.
  - Builder failure never breaks the legacy path. The top-level
    :func:`try_build_shadow_bundle` catches construction errors and
    returns ``None`` + a diagnostic, mirroring ``dual_emit`` semantics.

Zone: contracts — pure data, no market logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.decision_bundle import DecisionBundle
from contracts.layer_envelope import EvidencePlane, LayerEnvelope
from contracts.runtime_projection import EnvelopeCollection

# Plane → DecisionBundle field name.
_PLANE_TO_FIELD: dict[EvidencePlane, str] = {
    "context": "context_evidence",
    "alpha": "alpha_evidence",
    "validation": "validation_evidence",
    "risk": "risk_evidence",
    "portfolio": "portfolio_evidence",
    "economics": "economics_evidence",
    "meta": "meta_evidence",
    # "post_authority_veto" is deliberately NOT mapped — excluded from bundle.
}


def build_shadow_decision_bundle(
    collection: EnvelopeCollection,
    *,
    timeframe: str,
    runtime_context_ref: str,
    created_at: datetime | None = None,
) -> DecisionBundle:
    """Build a shadow :class:`DecisionBundle` from an envelope collection.

    Parameters
    ----------
    collection:
        Envelope store populated by ``dual_emit`` during the pipeline run.
    timeframe:
        The primary timeframe this decision is being evaluated on (e.g. ``"H1"``).
    runtime_context_ref:
        Opaque reference to the runtime context snapshot (stream seq, Redis
        key, etc.). Never pass raw account state here.
    created_at:
        Optional explicit timestamp. Defaults to ``datetime.now(UTC)``.

    Returns
    -------
    DecisionBundle
        A frozen bundle with envelopes grouped by plane. V11 envelopes are
        excluded. Bundle construction is deterministic: for the same
        collection (insertion order) + same ``created_at`` + same refs the
        returned bundle's ``summary()`` is identical.
    """
    buckets: dict[str, list[LayerEnvelope]] = {field: [] for field in _PLANE_TO_FIELD.values()}
    for env in collection.all_envelopes():
        field_name = _PLANE_TO_FIELD.get(env.plane)
        if field_name is None:
            # post_authority_veto (V11) — intentional skip.
            continue
        buckets[field_name].append(env)

    return DecisionBundle(
        signal_id=collection.signal_id,
        symbol=collection.symbol,
        timeframe=timeframe,
        runtime_context_ref=runtime_context_ref,
        context_evidence=buckets["context_evidence"],
        alpha_evidence=buckets["alpha_evidence"],
        validation_evidence=buckets["validation_evidence"],
        risk_evidence=buckets["risk_evidence"],
        portfolio_evidence=buckets["portfolio_evidence"],
        economics_evidence=buckets["economics_evidence"],
        meta_evidence=buckets["meta_evidence"],
        created_at=created_at or datetime.now(tz=UTC),
    )


def try_build_shadow_bundle(
    collection: EnvelopeCollection,
    *,
    timeframe: str,
    runtime_context_ref: str,
    created_at: datetime | None = None,
) -> tuple[DecisionBundle | None, dict[str, Any] | None]:
    """Safe builder: never raises into the caller.

    Mirrors ``dual_emit`` safety. If bundle construction fails (for any
    reason — validator rejection, schema mismatch, unexpected state), the
    function returns ``(None, diagnostic)``. The legacy pipeline path can
    call this freely without risk of breaking live trades.

    Returns
    -------
    tuple[DecisionBundle | None, dict | None]
        ``(bundle, None)`` on success, or ``(None, diagnostic_dict)`` on
        failure. Diagnostic contains ``error_type`` and ``error_message``.
    """
    try:
        bundle = build_shadow_decision_bundle(
            collection,
            timeframe=timeframe,
            runtime_context_ref=runtime_context_ref,
            created_at=created_at,
        )
        return bundle, None
    except Exception as exc:  # noqa: BLE001 — deliberate isolation boundary
        return None, {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "signal_id": collection.signal_id,
            "symbol": collection.symbol,
        }


__all__ = [
    "build_shadow_decision_bundle",
    "try_build_shadow_bundle",
]
