"""P0.5 Adapters: legacy layer output → ``LayerEnvelope``.

Zero-change projection. These helpers read the canonical dict/dataclass output
of existing ``L*_constitutional`` modules and project them into the Blueprint v2
envelope contract. No layer logic is mutated; no account-state is fabricated;
no direction is invented.

Authority invariants preserved here:
  - Plane mapping is fixed by constitutional doctrine (L1..L15 + V11).
  - ``WARN`` legacy status → ``DEGRADED`` envelope status (advisory, non-blocking
    unless blocker_codes are present).
  - ``blocker_codes`` and ``warning_codes`` from the legacy dict flow into the
    envelope's ``blockers``/``warnings`` verbatim (deduped by the envelope).
  - ``features``/``routing``/``audit`` become ``evidence`` namespaces. The
    envelope's own validator will reject any account-state leakage.
  - ``direction`` defaults to ``"NONE"``; only L12 authorises BUY/SELL.

Zone: contracts — validation-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from contracts.layer_envelope import (
    Direction,
    EvidencePlane,
    LayerEnvelope,
    LayerStatus,
)

# ── Plane mapping (constitutional doctrine) ───────────────────────────────
# Matches the `EvidencePlane` comments in layer_envelope.py and the Phase
# sequence in copilot-instructions.md §4.
_LAYER_PLANE: dict[str, EvidencePlane] = {
    "L1": "context",
    "L2": "alpha",
    "L3": "alpha",
    "L4": "alpha",
    "L5": "validation",
    "L6": "risk",
    "L7": "validation",
    "L8": "validation",
    "L9": "alpha",
    "L10": "portfolio",
    "L11": "economics",
    "L13": "meta",
    "L15": "meta",
    "V11": "post_authority_veto",
}

# Legacy layers emit PASS / WARN / FAIL. Envelope uses PASS / DEGRADED / FAIL / SKIPPED.
_STATUS_MAP: dict[str, LayerStatus] = {
    "PASS": "PASS",
    "OK": "PASS",
    "WARN": "DEGRADED",
    "DEGRADED": "DEGRADED",
    "FAIL": "FAIL",
    "ERROR": "FAIL",
    "SKIP": "SKIPPED",
    "SKIPPED": "SKIPPED",
}


def default_plane_for_layer(layer_id: str) -> EvidencePlane:
    """Return the canonical evidence plane for a given layer id.

    Raises ``KeyError`` if the layer id is not part of the 15-layer + V11
    doctrine. Callers that need a custom plane must pass it explicitly.
    """
    key = layer_id.strip().upper()
    return _LAYER_PLANE[key]


def _parse_iso(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        # Python's fromisoformat handles "YYYY-MM-DDTHH:MM:SS+00:00" natively.
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalize_status(raw: Any) -> LayerStatus:
    if raw is None:
        return "FAIL"
    key = str(raw).strip().upper()
    return _STATUS_MAP.get(key, "FAIL")


def _coerce_direction(raw: Any) -> Direction:
    if raw is None:
        return "NONE"
    key = str(raw).strip().upper()
    if key in ("BUY", "LONG"):
        return "BUY"
    if key in ("SELL", "SHORT"):
        return "SELL"
    if key in ("NEUTRAL",):
        return "NEUTRAL"
    return "NONE"


def _coerce_score(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def layer_dict_to_envelope(
    result: Mapping[str, Any] | Any,
    *,
    signal_id: str,
    symbol: str,
    plane: EvidencePlane | None = None,
    layer_id: str | None = None,
    module: str | None = None,
    stale_after_ms: int | None = None,
    direction: Direction | None = None,
    confidence: float | None = None,
) -> LayerEnvelope:
    """Project a legacy layer canonical-envelope dict into a ``LayerEnvelope``.

    Accepts either a ``Mapping`` (L2..L11 style) or any object exposing
    ``to_dict()`` (L1's ``L1ConstitutionalResult`` dataclass).

    The projection is non-destructive: ``features``, ``routing``, and ``audit``
    from the legacy output are placed under matching evidence namespaces. The
    envelope's own account-state validator is the final guard against leakage.
    """
    if not isinstance(result, Mapping):
        if hasattr(result, "to_dict") and callable(result.to_dict):
            result = result.to_dict()
        else:
            raise TypeError(
                f"layer_dict_to_envelope expects a Mapping or an object with .to_dict(); got {type(result).__name__}"
            )

    resolved_layer_id = (layer_id or str(result.get("layer") or "")).strip()
    if not resolved_layer_id:
        raise ValueError("layer_id could not be resolved from result or kwargs")

    resolved_plane: EvidencePlane = plane if plane is not None else default_plane_for_layer(resolved_layer_id)
    resolved_module = module or f"analysis.layers.{resolved_layer_id}_constitutional"

    evidence: dict[str, Any] = {}
    for key in ("features", "routing", "audit"):
        section = result.get(key)
        if isinstance(section, Mapping) and section:
            evidence[key] = dict(section)

    # Capture structural context fields that don't fit features/routing/audit
    # but carry useful routing signals for L12 (without leaking account state).
    for key in ("coherence_band", "fallback_class", "freshness_state", "warmup_state"):
        value = result.get(key)
        if value is not None:
            evidence.setdefault("context", {})[key] = value

    finished_at = _parse_iso(result.get("timestamp"))
    started_at = _parse_iso(result.get("started_at")) or finished_at

    kwargs: dict[str, Any] = {
        "signal_id": signal_id,
        "symbol": symbol,
        "layer_id": resolved_layer_id,
        "module": resolved_module,
        "plane": resolved_plane,
        "status": _normalize_status(result.get("status")),
        "score": _coerce_score(result.get("coherence_score") or result.get("score")),
        "confidence": confidence,
        "direction": _coerce_direction(direction if direction is not None else result.get("direction")),
        "blockers": list(result.get("blocker_codes") or result.get("blockers") or []),
        "warnings": list(result.get("warning_codes") or result.get("warnings") or []),
        "evidence": evidence,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if stale_after_ms is not None:
        kwargs["stale_after_ms"] = int(stale_after_ms)

    return LayerEnvelope(**kwargs)


__all__ = [
    "default_plane_for_layer",
    "layer_dict_to_envelope",
]
