"""Volatility Clustering Model — GARCH-style autocorrelation detector.

Detects volatility persistence (clustering) by analyzing autocorrelation
of squared returns across multiple lags. Produces a risk_multiplier for
L6 Risk adjustment.

Authority: ANALYSIS-ONLY. No execution side-effects.
           Enriches L6 Risk (currently PLACEHOLDER).
           Does NOT overlap macro_volatility_engine (VIX regime state)
           or L1 (ATR-based vol) — this measures temporal persistence
           of volatility itself (GARCH-style behavior).

Bug fixes over original draft:
    ✅ Multi-lag autocorrelation (lags 1–5, not single lag-1)
    ✅ NaN guard: constant returns → zero variance → safe fallback
    ✅ risk_multiplier capped at configurable max (default 1.5)
    ✅ risk_multiplier linear scaling (not raw 1 + autocorr)
    ✅ Minimum data length guard (≥ 20 returns)
    ✅ Ljung-Box proxy for clustering strength assessment
    ✅ Proper demeaned autocorrelation (not np.corrcoef shortcut)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

_DEFAULT_MAX_LAG = 5
_DEFAULT_CLUSTERING_THRESHOLD = 0.20
_DEFAULT_MAX_RISK_MULT = 1.5
_DEFAULT_MIN_RETURNS = 20


@dataclass(frozen=True)
class VolatilityClusterResult:
    """Immutable result of volatility clustering analysis."""

    clustering_detected: bool
    vol_persistence: float                          # Mean autocorr of squared returns
    risk_multiplier: float                          # Suggested risk scaling [1.0, max]
    per_lag_autocorrelation: dict[int, float]        # Autocorrelation per lag
    ljung_box_proxy: float                           # Sum of squared autocorrs
    sample_size: int                                 # Returns analyzed

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L6 risk consumption."""
        return {
            "clustering_detected": self.clustering_detected,
            "vol_persistence": self.vol_persistence,
            "risk_multiplier": self.risk_multiplier,
            "per_lag_autocorrelation": dict(self.per_lag_autocorrelation),
            "ljung_box_proxy": self.ljung_box_proxy,
            "sample_size": self.sample_size,
        }


class VolatilityClusteringModel:
    """GARCH-style volatility clustering detector.

    Analyzes autocorrelation of squared returns at multiple lags to detect
    temporal persistence of volatility — a signature of clustered regimes.

    Parameters
    ----------
    max_lag : int
        Maximum autocorrelation lag (default 5). Actual lags capped at
        len(returns) // 4 to avoid noisy tail estimates.
    clustering_threshold : float
        Mean autocorrelation above which clustering is declared. Default 0.20.
    max_risk_multiplier : float
        Cap on risk multiplier output. Default 1.5.
    min_returns : int
        Minimum returns required. Default 20.
    """

    def __init__(
        self,
        max_lag: int = _DEFAULT_MAX_LAG,
        clustering_threshold: float = _DEFAULT_CLUSTERING_THRESHOLD,
        max_risk_multiplier: float = _DEFAULT_MAX_RISK_MULT,
        min_returns: int = _DEFAULT_MIN_RETURNS,
    ) -> None:
        self._max_lag = max(1, max_lag)
        self._clustering_threshold = clustering_threshold
        self._max_risk_mult = max_risk_multiplier
        self._min_returns = max(3, min_returns)

    # ── Public API ───────────────────────────────────────────────────────────

    def analyze(self, returns: list[float]) -> VolatilityClusterResult:
        """Analyze volatility clustering from return series.

        Args:
            returns: Per-period returns (daily, per-trade, etc.).

        Returns:
            VolatilityClusterResult with persistence and risk multiplier.

        Raises:
            ValueError: If fewer than ``min_returns`` provided.
        """
        arr = np.asarray(returns, dtype=np.float64)

        if len(arr) < self._min_returns:
            raise ValueError(
                f"Minimum {self._min_returns} returns required, got {len(arr)}"
            )

        # ── Squared returns (proxy for variance process) ─────────────
        squared = arr ** 2

        # Demean for proper autocorrelation
        sq_mean = float(np.mean(squared))
        sq_demeaned = squared - sq_mean
        sq_var = float(np.var(squared, ddof=0))

        # ── Multi-lag autocorrelation ────────────────────────────────
        # Cap at 25% of data length to avoid noisy estimates
        effective_max = min(self._max_lag, len(arr) // 4)
        effective_max = max(1, effective_max)

        per_lag: dict[int, float] = {}

        if sq_var > 0.0:
            for lag in range(1, effective_max + 1):
                if lag >= len(sq_demeaned):
                    per_lag[lag] = 0.0
                    continue
                # Manual autocorrelation: cov(x[:-lag], x[lag:]) / var(x)
                autocov = float(np.mean(sq_demeaned[:-lag] * sq_demeaned[lag:]))
                ac = autocov / sq_var
                # Clamp numerical noise
                ac = max(-1.0, min(1.0, ac))
                per_lag[lag] = round(ac, 4)
        else:
            # Zero variance (constant returns) → no clustering
            for lag in range(1, effective_max + 1):
                per_lag[lag] = 0.0

        # ── Aggregate persistence ────────────────────────────────────
        ac_values = list(per_lag.values())
        vol_persistence = float(np.mean(ac_values)) if ac_values else 0.0

        # ── Ljung-Box proxy (sum of squared autocorrelations) ────────
        ljung_box_proxy = float(sum(ac ** 2 for ac in ac_values))

        # ── Detection ────────────────────────────────────────────────
        clustering_detected = vol_persistence > self._clustering_threshold

        # ── Risk multiplier ──────────────────────────────────────────
        # Linear scaling from 1.0 at threshold to max at persistence=1.0
        if clustering_detected and vol_persistence > 0.0:
            excess = vol_persistence - self._clustering_threshold
            scale_range = 1.0 - self._clustering_threshold  # normalizer
            fraction = excess / scale_range if scale_range > 0 else 0.0
            raw_mult = 1.0 + fraction * (self._max_risk_mult - 1.0)
            risk_multiplier = min(raw_mult, self._max_risk_mult)
        else:
            risk_multiplier = 1.0

        return VolatilityClusterResult(
            clustering_detected=clustering_detected,
            vol_persistence=round(vol_persistence, 4),
            risk_multiplier=round(risk_multiplier, 3),
            per_lag_autocorrelation=per_lag,
            ljung_box_proxy=round(ljung_box_proxy, 4),
            sample_size=len(arr),
        )
