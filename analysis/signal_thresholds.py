"""Single source of truth for signal risk/reward thresholds.

Every module in the signal pipeline (microboost engines, execution gate, gate
adapter, block finalizer, emitter, enrichment) imports the minimum reward:risk
from here so the policy can never drift between layers again.

Runtime override:
    SIGNAL_MIN_RR   -> minimum reward:risk, measured at TP1 (default 1.5 => 1:1.5)
    SIGNAL_TP1_RR   -> fixed RR used to project TP1 (defaults to SIGNAL_MIN_RR)
"""

from __future__ import annotations

import os


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Minimum reward:risk for a signal to be execution-valid. The TP1 target is
# projected at this RR against the single sl_safe stop, so the minimum is
# measured at TP1 (1:1.5 by default).
SIGNAL_MIN_RR: float = _env_float("SIGNAL_MIN_RR", 1.5)

# Fixed RR used to project TP1. Kept equal to the minimum so TP1 is the anchor.
TP1_TARGET_RR: float = _env_float("SIGNAL_TP1_RR", SIGNAL_MIN_RR)
