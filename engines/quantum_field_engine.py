from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


@dataclass
class FieldSnapshot:
    valid: bool
    field_energy: float
    field_bias: float
    energy_drift: float
    vwap_strength: float
    stability_index: float


class QuantumFieldEngine:
    def evaluate(self, prices: list[float], volumes: list[float]) -> FieldSnapshot:
        if len(prices) < 20:
            return FieldSnapshot(False, 0.0, 0.0, 0.0, 0.0, 0.0)

        if np is not None:
            p = np.array(prices[-40:], dtype=float)
            v = np.array(volumes[-40:] if volumes else [1.0] * min(40, len(prices)), dtype=float)
            energy = float(np.std(p[-20:]) / max(np.mean(p[-20:]), 1e-9))
            bias = float((p[-1] - np.mean(p[-20:])) / max(np.mean(p[-20:]), 1e-9))
            early = float(np.std(p[:20]) / max(np.mean(p[:20]), 1e-9))
            drift = energy - early
            vwap = float(np.sum(p * v) / max(np.sum(v), 1e-9))
            vwap_strength = float((p[-1] - vwap) / max(vwap, 1e-9))
            stability = float(1.0 / (1.0 + np.std(np.diff(p[-10:]))))
        else:
            p = prices[-40:]
            v = volumes[-40:] if volumes else [1.0] * len(p)
            energy = pstdev(p[-20:]) / max(fmean(p[-20:]), 1e-9)
            bias = (p[-1] - fmean(p[-20:])) / max(fmean(p[-20:]), 1e-9)
            early = pstdev(p[:20]) / max(fmean(p[:20]), 1e-9)
            drift = energy - early
            vwap = sum(px * vol for px, vol in zip(p, v, strict=False)) / max(sum(v), 1e-9)
            vwap_strength = (p[-1] - vwap) / max(vwap, 1e-9)
            diffs = [p[idx] - p[idx - 1] for idx in range(1, len(p[-10:]))]
            stability = 1.0 / (1.0 + (pstdev(diffs) if len(diffs) > 1 else 0.0))

        return FieldSnapshot(
            True,
            round(energy, 6),
            round(max(-1.0, min(1.0, bias)), 6),
            round(drift, 6),
            round(vwap_strength, 6),
            round(max(0.0, min(1.0, stability)), 6),
        )

    @staticmethod
    def export(snapshot: FieldSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "field_energy": snapshot.field_energy,
            "field_bias": snapshot.field_bias,
            "energy_drift": snapshot.energy_drift,
            "vwap_strength": snapshot.vwap_strength,
            "stability_index": snapshot.stability_index,
        }
