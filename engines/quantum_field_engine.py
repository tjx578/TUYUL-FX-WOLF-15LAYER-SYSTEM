"""
Quantum Field Engine v2.0 (analysis-only).

NO BUY / SELL / EXECUTE - analysis only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import math

logger = logging.getLogger(__name__)

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    logger.warning("numpy not available - using pure-Python fallback")


class QuantumFieldEngine:
    """Compute field metrics from price and optional volume series."""

    def __init__(
        self,
        energy_window: int = 20,
        bias_window: int = 50,
        drift_window: int = 10,
    ) -> None:
        self.energy_window = energy_window
        self.bias_window = bias_window
        self.drift_window = drift_window

    def evaluate(self, prices: Any, volumes: Optional[Any] = None) -> Dict[str, Any]:
        """Evaluate field state from market data."""
        if prices is None or (hasattr(prices, "__len__") and len(prices) < 5):
            return {
                "valid": False,
                "reason": "insufficient_price_data",
                "min_required": 5,
                "received": len(prices) if prices is not None else 0,
            }

        if HAS_NUMPY:
            return self._evaluate_numpy(prices, volumes)
        return self._evaluate_pure(prices)

    def _evaluate_numpy(self, prices: Any, volumes: Optional[Any]) -> Dict[str, Any]:
        p = np.array(prices, dtype=np.float64)
        n = len(p)

        e_win = min(self.energy_window, n)
        field_energy = float(np.std(p[-e_win:]))

        if n >= e_win + self.drift_window:
            energies = [
                float(np.std(p[i : i + e_win]))
                for i in range(n - e_win - self.drift_window, n - e_win + 1)
            ]
            energy_drift = (energies[-1] - energies[0]) / max(len(energies), 1)
            drift_vol = float(np.std(energies)) if len(energies) > 1 else 0.001
        else:
            energy_drift = 0.0
            drift_vol = 0.001

        b_win = min(self.bias_window, n)
        price_mean = float(np.mean(p[-b_win:]))
        field_bias = float((p[-1] - price_mean) / price_mean) if price_mean != 0 else 0.0

        if volumes is not None and len(volumes) >= n:
            v = np.array(volumes[-n:], dtype=np.float64)
            vol_sum = np.sum(v)
            if vol_sum > 0:
                vwap = float(np.sum(p * v) / vol_sum)
                vwap_strength = float((p[-1] - vwap) / vwap) if vwap != 0 else 0.0
            else:
                vwap = price_mean
                vwap_strength = 0.0
        else:
            weights = np.linspace(0.5, 1.5, n)
            vwap = float(np.average(p, weights=weights))
            vwap_strength = float((p[-1] - vwap) / vwap) if vwap != 0 else 0.0

        stability = max(0.0, min(1.0, 1.0 / (1.0 + abs(drift_vol) * 100)))

        return {
            "valid": True,
            "field_energy": round(field_energy, 6),
            "field_bias": round(field_bias, 6),
            "energy_drift": round(energy_drift, 8),
            "vwap_strength": round(vwap_strength, 6),
            "stability_index": round(stability, 4),
            "price_mean": round(price_mean, 5),
            "vwap": round(vwap, 5),
            "data_points": n,
        }

    def _evaluate_pure(self, prices: Any) -> Dict[str, Any]:
        p = list(prices)
        n = len(p)

        e_win = min(self.energy_window, n)
        recent = p[-e_win:]
        mean_r = sum(recent) / e_win
        field_energy = math.sqrt(sum((x - mean_r) ** 2 for x in recent) / e_win)

        b_win = min(self.bias_window, n)
        price_mean = sum(p[-b_win:]) / b_win
        field_bias = (p[-1] - price_mean) / price_mean if price_mean != 0 else 0.0

        if n >= 20:
            e1 = self._std(p[-20:-10])
            e2 = self._std(p[-10:])
            energy_drift = e2 - e1
        else:
            energy_drift = 0.0

        stability = max(0.0, min(1.0, 1.0 / (1.0 + abs(energy_drift) * 100)))

        return {
            "valid": True,
            "field_energy": round(field_energy, 6),
            "field_bias": round(field_bias, 6),
            "energy_drift": round(energy_drift, 8),
            "vwap_strength": round(field_bias * 0.8, 6),
            "stability_index": round(stability, 4),
            "price_mean": round(price_mean, 5),
            "data_points": n,
        }

    @staticmethod
    def _std(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean_val = sum(values) / len(values)
        return math.sqrt(sum((x - mean_val) ** 2 for x in values) / len(values))


__all__ = ["QuantumFieldEngine"]
