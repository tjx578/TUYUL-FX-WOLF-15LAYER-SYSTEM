"""Quantum field engine."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev


@dataclass
class FieldResult:
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
