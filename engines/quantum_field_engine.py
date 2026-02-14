"""Quantum field engine with numpy acceleration and pure-python fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import numpy as np
except Exception:  # pragma: no cover
"""Quantum field engine with numpy acceleration and pure Python fallback."""

import math

from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
except Exception:
    np = None


@dataclass
class FieldResult:
class FieldReport:
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
        if len(prices) < self.energy_window + self.drift_window + 2:
            return FieldResult(0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient_data"})

        if np is not None:
            arr_p = np.array(prices, dtype=float)
            arr_v = np.array(volumes[-len(prices) :], dtype=float) if volumes else np.ones_like(arr_p)
            energy_series = np.std(
                np.lib.stride_tricks.sliding_window_view(arr_p, self.energy_window), axis=1
            )
            field_energy = float(energy_series[-1] / max(arr_p[-1], 1e-8))
            field_bias = float((arr_p[-1] - np.mean(arr_p[-self.energy_window :])) / arr_p[-1])
            energy_drift = float(energy_series[-1] - energy_series[-self.drift_window])
            vwap = float(np.sum(arr_p[-self.energy_window :] * arr_v[-self.energy_window :])) / float(
                np.sum(arr_v[-self.energy_window :])
            )
        else:
            win = prices[-self.energy_window :]
            mean_p = sum(win) / len(win)
            variance = sum((p - mean_p) ** 2 for p in win) / len(win)
            field_energy = (variance ** 0.5) / max(prices[-1], 1e-8)
            field_bias = (prices[-1] - mean_p) / max(prices[-1], 1e-8)
            prev = prices[-(self.energy_window + self.drift_window) : -self.drift_window]
            prev_mean = sum(prev) / len(prev)
            prev_var = sum((p - prev_mean) ** 2 for p in prev) / len(prev)
            energy_drift = variance ** 0.5 - prev_var ** 0.5
            if volumes:
                sub_prices = prices[-self.energy_window :]
                sub_vol = volumes[-self.energy_window :]
                vwap = sum(p * v for p, v in zip(sub_prices, sub_vol)) / max(sum(sub_vol), 1e-8)
            else:
                vwap = mean_p

        vwap_strength = (prices[-1] - vwap) / max(prices[-1], 1e-8)
        stability = 1.0 / (1.0 + abs(energy_drift) * 15)

        return FieldResult(
            field_energy=round(field_energy, 6),
            field_bias=round(field_bias, 6),
            energy_drift=round(energy_drift, 6),
            vwap_strength=round(vwap_strength, 6),
            stability_index=round(max(0.0, min(1.0, stability)), 6),
            details={"backend": "numpy" if np is not None else "python"},
        )

    @staticmethod
    def export(result: FieldResult) -> Dict[str, Any]:
        return {
            "field_energy": result.field_energy,
            "field_bias": result.field_bias,
            "energy_drift": result.energy_drift,
            "vwap_strength": result.vwap_strength,
            "stability_index": result.stability_index,
            "details": result.details,
        }
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
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class QuantumField:
    field_energy: float
    bias: float
    stability: float


class QuantumFieldEngine:
    """Compute aggregate field state from directional and noise components."""

    def evaluate(self, state: Mapping[str, Any]) -> QuantumField:
        direction = float(state.get("directional_pressure", 0.0))
        coherence = max(0.0, min(1.0, float(state.get("signal_coherence", 0.5))))
        noise = max(0.0, min(1.0, float(state.get("market_noise", 0.5))))

        energy = max(0.0, min(1.0, (abs(direction) * 0.55) + coherence * 0.45))
        bias = max(-1.0, min(1.0, direction))
        stability = max(0.0, min(1.0, coherence * (1.0 - noise)))
        return QuantumField(field_energy=energy, bias=bias, stability=stability)
