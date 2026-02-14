from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FusionPrecision:
    precision_weight: float
    ema_alignment_score: float


class FusionPrecisionEngine:
    """Estimate entry precision from weighting and EMA agreement."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionPrecision:
        weights = state.get("precision_weights", [0.5, 0.5])
        if not isinstance(weights, list) or not weights:
            weights = [0.5, 0.5]
        mean_weight = sum(float(w) for w in weights) / len(weights)
        ema_fast = float(state.get("ema_fast", 0.0))
        ema_slow = float(state.get("ema_slow", 0.0))
        alignment = max(0.0, min(1.0, 1.0 - min(1.0, abs(ema_fast - ema_slow))))

        return FusionPrecision(
            precision_weight=max(0.0, min(1.0, mean_weight)),
            ema_alignment_score=alignment,
        )
