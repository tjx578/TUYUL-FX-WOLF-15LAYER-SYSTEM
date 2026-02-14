"""Quantum field engine with numpy acceleration and pure Python fallback."""

import math

from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
except Exception:
    np = None


@dataclass
class FieldReport:
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float
    details: dict[str, Any]


class QuantumFieldEngine:
    def __init__(self, energy_window: int = 20, drift_window: int = 8) -> None:
        self.energy_window = energy_window
        self.drift_window = drift_window

    def evaluate(self, prices: list[float], volumes: list[float] | None = None) -> FieldReport:
        if len(prices) < self.energy_window + 5:
            return FieldReport(0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient_data"})

        if np is not None:
            arr = np.asarray(prices, dtype=float)
            energy = float(np.std(arr[-self.energy_window :]))
            mean_price = float(np.mean(arr[-self.energy_window :]))
            bias = (arr[-1] - mean_price) / max(mean_price, 1e-9)
            energies = [
                float(np.std(arr[i - self.energy_window : i]))
                for i in range(self.energy_window, len(arr))
            ]
        else:
            window = prices[-self.energy_window :]
            mean_price = sum(window) / len(window)
            energy = self._stdev(window)
            bias = (prices[-1] - mean_price) / max(mean_price, 1e-9)
            energies = [
                self._stdev(prices[i - self.energy_window : i])
                for i in range(self.energy_window, len(prices))
            ]

        drift = 0.0
        if len(energies) > self.drift_window:
            old = sum(energies[-self.drift_window - 1 : -1]) / self.drift_window
            new = sum(energies[-self.drift_window :]) / self.drift_window
            drift = (new - old) / max(old, 1e-9)

        if volumes and len(volumes) == len(prices):
            wsum = sum(
                v * p for p, v in zip(prices[-self.energy_window :], volumes[-self.energy_window :], strict=False)
            )
            vsum = sum(volumes[-self.energy_window :])
            vwap = wsum / max(vsum, 1e-9)
        else:
            vwap = mean_price
        vwap_strength = (prices[-1] - vwap) / max(vwap, 1e-9)

        drift_vol = (
            self._stdev(energies[-self.drift_window :])
            if len(energies) >= self.drift_window
            else 0.0
        )
        stability = 1.0 / (1.0 + abs(drift) + drift_vol)

        return FieldReport(
            field_energy=round(energy, 6),
            field_bias=round(bias, 6),
            energy_drift=round(drift, 6),
            vwap_strength=round(vwap_strength, 6),
            stability_index=round(stability, 4),
            details={"backend": "numpy" if np is not None else "python", "vwap": round(vwap, 6)},
        )

    def _stdev(self, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)
