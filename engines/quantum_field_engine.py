"""Quantum field proxy engine."""
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
"""Quantum field engine."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev
"""Quantum field engine with numpy acceleration and pure-python fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence
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
    valid: bool
class FieldReport:
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float


class QuantumFieldEngine:
    def evaluate(self, prices: list[float], volumes: list[float]) -> FieldResult:
        if len(prices) < 3:
            return FieldResult(0.0, 0.0, 0.0, 0.0, 0.0)
        window = prices[-20:] if len(prices) > 20 else prices
        mean = fmean(window)
        energy = pstdev(window)
        bias = (prices[-1] - mean) / mean if mean else 0.0
        short_mean = fmean(prices[-5:])
        long_mean = fmean(prices[-15:]) if len(prices) >= 15 else mean
        drift = (short_mean - long_mean) / long_mean if long_mean else 0.0
        if volumes and len(volumes) == len(prices):
            num = sum(p * v for p, v in zip(prices[-20:], volumes[-20:], strict=False))
            den = sum(volumes[-20:])
            vwap = num / den if den else mean
        else:
            vwap = mean
        vwap_strength = abs((prices[-1] - vwap) / vwap) if vwap else 0.0
        stability = 1.0 / (1.0 + abs(drift) * 25.0)
        return FieldResult(
            round(energy, 6),
            round(bias, 6),
            round(drift, 6),
            round(vwap_strength, 6),
            round(stability, 4),
        )
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
