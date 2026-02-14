"""Quantum field engine with numpy acceleration and pure-python fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


@dataclass
class FieldResult:
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float
    details: dict[str, Any] = field(default_factory=dict)


class QuantumFieldEngine:
    def __init__(self, energy_window: int = 20, drift_window: int = 10) -> None:
        self.energy_window = energy_window
        self.drift_window = drift_window

    def evaluate(self, prices: list[float], volumes: list[float]) -> FieldResult:
        if len(prices) < self.energy_window + self.drift_window + 2:
            return FieldResult(0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient_data"})

        if np is not None:
            arr_p = np.array(prices, dtype=float)
            arr_v = (
                np.array(volumes[-len(prices) :], dtype=float) if volumes else np.ones_like(arr_p)
            )
            # Use a local window size to keep all rolling computations consistent and safe
            window = min(self.energy_window, arr_p.shape[0])
            energy_series = np.std(np.lib.stride_tricks.sliding_window_view(arr_p, window), axis=1)
            field_energy = float(energy_series[-1] / max(arr_p[-1], 1e-8))
            field_bias = float((arr_p[-1] - np.mean(arr_p[-window:])) / arr_p[-1])
            # Calculate drift by comparing current energy to energy drift_window steps back
            # Clamp to ensure we don't access beyond the available series
            if len(energy_series) > self.drift_window:
                energy_drift = float(energy_series[-1] - energy_series[-(self.drift_window + 1)])
            else:
                energy_drift = 0.0
            vwap = float(np.sum(arr_p[-window:] * arr_v[-window:])) / float(np.sum(arr_v[-window:]))
        else:
            win = prices[-self.energy_window :]
            mean_p = sum(win) / len(win)
            variance = sum((p - mean_p) ** 2 for p in win) / len(win)
            field_energy = (variance**0.5) / max(prices[-1], 1e-8)
            field_bias = (prices[-1] - mean_p) / max(prices[-1], 1e-8)
            prev = prices[-(self.energy_window + self.drift_window) : -self.drift_window]
            prev_mean = sum(prev) / len(prev)
            prev_var = sum((p - prev_mean) ** 2 for p in prev) / len(prev)
            energy_drift = variance**0.5 - prev_var**0.5
            if volumes:
                sub_prices = prices[-self.energy_window :]
                sub_vol = volumes[-self.energy_window :]
                vwap = sum(p * v for p, v in zip(sub_prices, sub_vol, strict=False)) / max(
                    sum(sub_vol), 1e-8
                )
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
    def export(result: FieldResult) -> dict[str, Any]:
        return {
            "field_energy": result.field_energy,
            "field_bias": result.field_bias,
            "energy_drift": result.energy_drift,
            "vwap_strength": result.vwap_strength,
            "stability_index": result.stability_index,
            "details": result.details,
        }
