"""Signal conditioning utilities for microstructure-noise mitigation.

Zone: analysis-only. No execution side-effects.

This module prepares cleaner return series for downstream inference engines
(e.g., L7 Monte Carlo) by applying robust clipping, EMA smoothing, and
noise diagnostics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median, pstdev
from typing import Any


@dataclass(frozen=True)
class SignalConditioningConfig:
    """Configuration for return-series signal conditioning."""

    enabled: bool = True
    ema_span: int = 5
    outlier_mad_scale: float = 6.0
    min_samples: int = 20
    adaptive_sampling: bool = True
    high_noise_ratio: float = 0.65
    high_noise_stride: int = 2


@dataclass(frozen=True)
class ConditionedSignal:
    """Conditioned return series plus diagnostics."""

    raw_returns: list[float]
    conditioned_returns: list[float]
    raw_volatility: float
    realized_volatility: float
    noise_ratio: float
    microstructure_quality_score: float
    sampling_stride: int

    def diagnostics(self) -> dict[str, float | int]:
        return {
            "raw_volatility": round(self.raw_volatility, 8),
            "realized_volatility": round(self.realized_volatility, 8),
            "noise_ratio": round(self.noise_ratio, 6),
            "microstructure_quality_score": round(self.microstructure_quality_score, 6),
            "sampling_stride": self.sampling_stride,
            "samples_in": len(self.raw_returns),
            "samples_out": len(self.conditioned_returns),
        }


class SignalConditioner:
    """Condition return or price series for probabilistic inference."""

    def __init__(self, config: SignalConditioningConfig | None = None) -> None:
        super().__init__()
        self._cfg = config or SignalConditioningConfig()

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> SignalConditioner:
        cfg = config or {}
        return cls(
            SignalConditioningConfig(
                enabled=bool(cfg.get("enabled", True)),
                ema_span=max(2, int(cfg.get("ema_span", 5))),
                outlier_mad_scale=max(1.0, float(cfg.get("outlier_mad_scale", 6.0))),
                min_samples=max(5, int(cfg.get("min_samples", 20))),
                adaptive_sampling=bool(cfg.get("adaptive_sampling", True)),
                high_noise_ratio=max(0.0, min(1.0, float(cfg.get("high_noise_ratio", 0.65)))),
                high_noise_stride=max(1, int(cfg.get("high_noise_stride", 2))),
            )
        )

    def condition_prices(self, prices: list[float]) -> ConditionedSignal:
        """Convert price series to log returns, then condition."""
        if len(prices) < 2:
            return self._empty_result([])

        returns: list[float] = []
        for i in range(1, len(prices)):
            prev = float(prices[i - 1])
            cur = float(prices[i])
            if prev <= 0.0 or cur <= 0.0:
                continue
            returns.append(math.log(cur / prev))
        return self.condition_returns(returns)

    def condition_returns(self, returns: list[float]) -> ConditionedSignal:
        """Apply robust filtering + smoothing on return series."""
        cleaned = [float(r) for r in returns if math.isfinite(float(r))]
        if len(cleaned) < 2:
            return self._empty_result(cleaned)

        if not self._cfg.enabled:
            vol = self._volatility(cleaned)
            return ConditionedSignal(
                raw_returns=cleaned,
                conditioned_returns=cleaned,
                raw_volatility=vol,
                realized_volatility=vol,
                noise_ratio=0.0,
                microstructure_quality_score=1.0,
                sampling_stride=1,
            )

        clipped = self._mad_clip(cleaned)
        smoothed = self._ema(clipped)

        raw_vol = self._volatility(cleaned)
        cond_vol = self._volatility(smoothed)
        noise_ratio = self._noise_ratio(raw_vol, cond_vol)

        stride = 1
        if self._cfg.adaptive_sampling and noise_ratio >= self._cfg.high_noise_ratio:
            stride = self._cfg.high_noise_stride
        conditioned = smoothed[::stride] if stride > 1 else smoothed

        sample_factor = min(1.0, len(conditioned) / float(self._cfg.min_samples))
        quality = max(0.0, min(1.0, (1.0 - noise_ratio) * sample_factor))

        return ConditionedSignal(
            raw_returns=cleaned,
            conditioned_returns=conditioned,
            raw_volatility=raw_vol,
            realized_volatility=cond_vol,
            noise_ratio=noise_ratio,
            microstructure_quality_score=quality,
            sampling_stride=stride,
        )

    @staticmethod
    def _volatility(series: list[float]) -> float:
        if len(series) < 2:
            return 0.0
        return float(pstdev(series))

    def _mad_clip(self, series: list[float]) -> list[float]:
        center = median(series)
        mad = median(abs(x - center) for x in series)
        if mad <= 0.0:
            return list(series)

        clip_radius = self._cfg.outlier_mad_scale * mad
        low = center - clip_radius
        high = center + clip_radius
        return [min(high, max(low, x)) for x in series]

    def _ema(self, series: list[float]) -> list[float]:
        if not series:
            return []
        alpha = 2.0 / (self._cfg.ema_span + 1.0)
        out: list[float] = [series[0]]
        prev = series[0]
        for x in series[1:]:
            prev = (alpha * x) + ((1.0 - alpha) * prev)
            out.append(prev)
        return out

    @staticmethod
    def _noise_ratio(raw_vol: float, conditioned_vol: float) -> float:
        if raw_vol <= 0.0:
            return 0.0
        ratio = (raw_vol - conditioned_vol) / raw_vol
        return max(0.0, min(1.0, ratio))

    @staticmethod
    def _empty_result(raw: list[float]) -> ConditionedSignal:
        return ConditionedSignal(
            raw_returns=raw,
            conditioned_returns=raw,
            raw_volatility=0.0,
            realized_volatility=0.0,
            noise_ratio=0.0,
            microstructure_quality_score=0.0,
            sampling_stride=1,
        )


__all__ = [
    "ConditionedSignal",
    "SignalConditioner",
    "SignalConditioningConfig",
]
