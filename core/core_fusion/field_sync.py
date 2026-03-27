"""Field Sync -- Context resolution and synchronization."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ._utils import _clamp01


def resolve_field_context(
    pair: str = "XAUUSD",
    timeframe: str = "H4",
    field_state: str | None = None,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if field_override:
        ctx = dict(field_override)
        ctx.setdefault("pair", pair)
        ctx.setdefault("timeframe", timeframe)
        ctx.setdefault("lambda_esi", lambda_esi)
        return ctx
    integrity = _clamp01((alpha + beta + gamma) / 3.0)
    return {
        "pair": pair,
        "timeframe": timeframe,
        "field_state": field_state or "neutral",
        "coherence": 0.95,
        "resonance": 0.88,
        "phase": "stable",
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "lambda_esi": lambda_esi,
        "field_integrity": round(integrity, 4),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def sync_field_state(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    merged = {**target, **source}
    merged["sync_timestamp"] = datetime.now(UTC).isoformat()
    return merged
