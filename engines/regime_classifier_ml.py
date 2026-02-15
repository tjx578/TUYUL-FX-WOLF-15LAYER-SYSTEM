"""Regime Classifier -- Hurst-exponent + volatility-based regime detection.

Statistical regime detection without hardcoded SMA thresholds:
    TRENDING       (H > 0.60)  -- persistent price moves
    MEAN_REVERTING (H < 0.45)  -- oscillatory / range-bound
    TRANSITION     (otherwise) -- ambiguous / regime shift

Authority: ANALYSIS-ONLY. No execution side-effects.
           Enriches L1 Context as secondary confirmation.
           Does NOT replace L1 -- acts as a parallel signal.

Bug fixes over original draft:
    ✅ _hurst_exponent: log(0) crash guard when std returns zero
    ✅ _hurst_exponent: correct formula poly[0] (NOT poly[0] * 2.0)
    ✅ _hurst_exponent: Hurst clamped to [0, 1]
    ✅ vol_state: compare against np.percentile(abs(returns)) not raw returns
    ✅ Added LOW_VOL state (3-state volatility)
    ✅ Minimum price length guard (≥ 25)
    ✅ Positive-price and NaN/Inf validation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

_MIN_PRICES = 25  # Hurst needs lag range(2, 20) + enough returns


@dataclass(frozen=True)
class RegimeClassification:
    """Immutable result of regime classification."""

    regime: str               # TRENDING | MEAN_REVERTING | TRANSITION
    confidence: float         # 0.0-1.0 (distance from random walk H=0.5)
    volatility_state: str     # HIGH_VOL | NORMAL_VOL | LOW_VOL
    hurst_exponent: float     # Raw Hurst value [0, 1]
    volatility: float         # Std of returns
    momentum: float           # Mean return (directional lean)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L1 enrichment consumption."""
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "volatility_state": self.volatility_state,
            "hurst_exponent": self.hurst_exponent,
            "volatility": self.volatility,
            "momentum": self.momentum,
        }


class RegimeClassifier:
    """Statistical regime detector using Hurst exponent and volatility.

    Parameters
    ----------
    hurst_trending : float
        Hurst threshold above which TRENDING is classified. Default 0.60.
    hurst_mean_revert : float
        Hurst threshold below which MEAN_REVERTING is classified. Default 0.45.
    vol_high_percentile : float
        Percentile of |returns| above which HIGH_VOL. Default 75.
    vol_low_percentile : float
        Percentile of |returns| below which LOW_VOL. Default 25.
    min_lag : int
        Minimum lag for Hurst regression. Default 2.
    max_lag : int
        Maximum lag for Hurst regression. Default 20.
    """

    def __init__(
        self,
        hurst_trending: float = 0.60,
        hurst_mean_revert: float = 0.45,
        vol_high_percentile: float = 75.0,
        vol_low_percentile: float = 25.0,
        min_lag: int = 2,
        max_lag: int = 20,
    ) -> None:
        self._hurst_trending = hurst_trending
        self._hurst_mean_revert = hurst_mean_revert
        self._vol_high_pct = vol_high_percentile
        self._vol_low_pct = vol_low_percentile
        self._min_lag = min_lag
        self._max_lag = max_lag

    # ── Public API ───────────────────────────────────────────────────────────

    def classify(self, prices: list[float]) -> RegimeClassification:
        """Classify market regime from price series.

        Args:
            prices: Chronological price data (≥ 25 values, all positive).

        Returns:
            RegimeClassification with regime, confidence, and volatility state.

        Raises:
            ValueError: If prices too short, contain non-positive, or NaN/Inf.
        """
        arr = np.asarray(prices, dtype=np.float64)

        if len(arr) < _MIN_PRICES:
            raise ValueError(
                f"Minimum {_MIN_PRICES} prices required, got {len(arr)}"
            )
        if np.any(~np.isfinite(arr)):
            raise ValueError("Prices contain NaN or Inf values")
        if np.any(arr <= 0):
            raise ValueError(
                "Prices must be positive (log-return computation requires > 0)"
            )

        # ── Returns ──────────────────────────────────────────────────
        returns = np.diff(arr) / arr[:-1]
        volatility = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        momentum = float(np.mean(returns))

        # ── Hurst exponent ───────────────────────────────────────────
        hurst = self._compute_hurst(arr)

        # ── Regime ───────────────────────────────────────────────────
        if hurst > self._hurst_trending:
            regime = "TRENDING"
        elif hurst < self._hurst_mean_revert:
            regime = "MEAN_REVERTING"
        else:
            regime = "TRANSITION"

        # ── Volatility state ─────────────────────────────────────────
        # FIX: compare volatility (scalar) against percentiles of |returns|
        abs_returns = np.abs(returns)
        p_high = float(np.percentile(abs_returns, self._vol_high_pct))
        p_low = float(np.percentile(abs_returns, self._vol_low_pct))

        if volatility > p_high:
            vol_state = "HIGH_VOL"
        elif volatility < p_low:
            vol_state = "LOW_VOL"
        else:
            vol_state = "NORMAL_VOL"

        # ── Confidence ───────────────────────────────────────────────
        # Distance from random walk (H=0.5), scaled to [0, 1]
        confidence = min(1.0, abs(hurst - 0.5) * 2.0)

        return RegimeClassification(
            regime=regime,
            confidence=round(confidence, 4),
            volatility_state=vol_state,
            hurst_exponent=round(hurst, 4),
            volatility=round(volatility, 8),
            momentum=round(momentum, 8),
        )

    # ── Private ──────────────────────────────────────────────────────────────

    def _compute_hurst(self, ts: np.ndarray) -> float:
        """Compute Hurst exponent via log-log regression of lagged std.

        Method: For each lag L, compute std(ts[L:] - ts[:-L]).
        Regress log(std) on log(lag). The slope IS the Hurst exponent.

        Returns 0.5 (random-walk assumption) on any computation failure.
        """
        effective_max = min(self._max_lag, len(ts) // 2)
        if effective_max < self._min_lag + 1:
            return 0.5  # Not enough data -> assume random walk

        valid_lags: list[int] = []
        valid_tau: list[float] = []

        for lag in range(self._min_lag, effective_max):
            diff = ts[lag:] - ts[:-lag]
            if len(diff) < 2:
                continue
            std_val = float(np.std(diff, ddof=1))
            # FIX: Guard log(0) -- skip lags with zero or negative std
            if std_val > 0.0 and np.isfinite(std_val):
                valid_lags.append(lag)
                valid_tau.append(std_val)

        if len(valid_lags) < 3:
            return 0.5  # Not enough valid lags for regression

        log_lags = np.log(np.array(valid_lags, dtype=np.float64))
        log_tau = np.log(np.array(valid_tau, dtype=np.float64))

        try:
            poly = np.polyfit(log_lags, log_tau, 1)
        except (np.linalg.LinAlgError, ValueError):
            return 0.5

        # FIX: Slope IS the Hurst exponent (NOT * 2.0)
        hurst = float(poly[0])

        # Clamp to theoretical [0, 1]
        return max(0.0, min(1.0, hurst))
