"""Quantum field proxy engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


@dataclass
class FieldResult:
    valid: bool
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumFieldEngine:
    def evaluate(self, prices: Sequence[float], volumes: Sequence[float]) -> FieldResult:
        if len(prices) < 25:
            return FieldResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient"})

        if np is not None:
            p = np.array(prices, dtype=float)
            v = np.array(volumes if volumes else [1.0] * len(prices), dtype=float)
            energy = float(np.std(p[-20:]))
            bias = float((p[-1] - np.mean(p[-20:])) / max(np.mean(p[-20:]), 1e-9))
            recent = [float(np.std(p[-w:])) for w in (8, 12, 20)]
        else:
            p = list(float(x) for x in prices)
            v = list(float(x) for x in (volumes if volumes else [1.0] * len(prices)))
            mean20 = sum(p[-20:]) / 20.0
            energy = (sum((x - mean20) ** 2 for x in p[-20:]) / 20.0) ** 0.5
            bias = (p[-1] - mean20) / max(mean20, 1e-9)
            recent = [self._std(p[-w:]) for w in (8, 12, 20)]

        drift = (recent[0] - recent[2]) / max(recent[2], 1e-9)
        vwap = sum(pp * vv for pp, vv in zip(prices[-20:], volumes[-20:])) / max(sum(volumes[-20:]), 1e-9)
        vwap_strength = (prices[-1] - vwap) / max(vwap, 1e-9)
        stab = 1.0 / (1.0 + abs(drift))

        return FieldResult(
            valid=True,
            field_energy=round(energy, 6),
            field_bias=round(bias, 6),
            energy_drift=round(drift, 6),
            vwap_strength=round(vwap_strength, 6),
            stability_index=round(stab, 4),
            details={
                "numpy_enabled": np is not None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _std(values: Sequence[float]) -> float:
        mean = sum(values) / max(len(values), 1)
        return (sum((x - mean) ** 2 for x in values) / max(len(values), 1)) ** 0.5
