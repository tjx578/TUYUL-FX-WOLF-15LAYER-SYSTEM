"""Field Sync -- Context resolution and synchronization."""

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional
from ._utils import _clamp01


def resolve_field_context(
    pair: str = "XAUUSD", timeframe: str = "H4",
    field_state: Optional[str] = None,
    alpha: float = 1.0, beta: float = 1.0, gamma: float = 1.0,
    lambda_esi: float = 0.06,
    field_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if field_override:
        ctx = dict(field_override)
        ctx.setdefault("pair", pair); ctx.setdefault("timeframe", timeframe)
        ctx.setdefault("lambda_esi", lambda_esi)
        return ctx
    integrity = _clamp01((alpha + beta + gamma) / 3.0)
    return {
        "pair": pair, "timeframe": timeframe,
        "field_state": field_state or "neutral",
        "coherence": 0.95, "resonance": 0.88, "phase": "stable",
        "alpha": alpha, "beta": beta, "gamma": gamma,
        "lambda_esi": lambda_esi, "field_integrity": round(integrity, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def sync_field_state(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**target, **source}
    merged["sync_timestamp"] = datetime.now(timezone.utc).isoformat()
    return merged
