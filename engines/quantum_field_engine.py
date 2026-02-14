"""Quantum field engine with numpy path and pure python fallback."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


@dataclass
class FieldResult:
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumFieldEngine:
    def __init__(self, energy_window: int = 20, drift_window: int = 10) -> None:
        self.energy_window = energy_window
        self.drift_window = drift_window

    def evaluate(self, prices: List[float], volumes: List[float]) -> FieldResult:
        prices = prices or [0.0]
        volumes = volumes or [1.0] * len(prices)

        if np is not None:
            price_arr = np.array(prices[-self.energy_window :], dtype=float)
            vol_arr = np.array(volumes[-len(price_arr) :], dtype=float)
            mean = float(np.mean(price_arr))
            energy = float(np.std(price_arr) / (mean if mean else 1.0))
            bias = float((price_arr[-1] - mean) / (mean if mean else 1.0))
            drift = self._drift_numpy(price_arr)
            vwap = float(np.sum(price_arr * vol_arr) / (np.sum(vol_arr) or 1.0))
            vwap_strength = abs((price_arr[-1] - vwap) / (vwap if vwap else 1.0))
        else:
            sample = prices[-self.energy_window :]
            mean = sum(sample) / len(sample)
            var = sum((x - mean) ** 2 for x in sample) / len(sample)
            energy = (var ** 0.5) / (mean if mean else 1.0)
            bias = (sample[-1] - mean) / (mean if mean else 1.0)
            drift = self._drift_python(sample)
            total_v = sum(volumes[-len(sample) :]) or 1.0
            vwap = sum(p * v for p, v in zip(sample, volumes[-len(sample) :])) / total_v
            vwap_strength = abs((sample[-1] - vwap) / (vwap if vwap else 1.0))

        stability = 1.0 / (1.0 + abs(drift) * 10.0)

        return FieldResult(
            field_energy=round(energy, 6),
            field_bias=round(max(-1.0, min(1.0, bias)), 6),
            energy_drift=round(drift, 6),
            vwap_strength=round(vwap_strength, 6),
            stability_index=round(max(0.0, min(1.0, stability)), 6),
            details={"backend": "numpy" if np is not None else "python"},
        )

    def _drift_numpy(self, values: Any) -> float:
        if len(values) < self.drift_window + 1:
            return 0.0
        tail = values[-(self.drift_window + 1) :]
        diffs = np.diff(tail)
        return float(np.mean(diffs) / (np.mean(tail) or 1.0))

    def _drift_python(self, values: List[float]) -> float:
        if len(values) < self.drift_window + 1:
            return 0.0
        tail = values[-(self.drift_window + 1) :]
        diffs = [b - a for a, b in zip(tail, tail[1:])]
        return (sum(diffs) / len(diffs)) / ((sum(tail) / len(tail)) or 1.0)


__all__ = ["FieldResult", "QuantumFieldEngine"]
