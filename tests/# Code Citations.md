# Code Citations

## License: GPL-2.0

<https://github.com/Thiti-Dev/search-algs-demonstration-gui/blob/6c486c498f3e459ede1ecdf01e25c8a18a806a4c/main_gui.py>

I'll implement all 4 production engines with the identified bug fixes, plus update `engines/__init__.py` and write comprehensive unit tests. Every file respects constitutional boundaries (analysis-only, no execution side-effects).

---

## 1. Walk-Forward Validation Engine

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\walk_forward_validation_engine.py
"""Walk-Forward Validation Engine — Out-of-Sample overfitting guard.

Slides a rolling train/test window across historical trade returns
to verify regime-robust, out-of-sample performance before deployment.

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds advisory metrics to L7/L12 — does NOT decide trades.

Bug fixes over original draft:
    ✅ ZeroDivisionError guard: empty losses list → safe PF computation
    ✅ stability_score clamped [0, 1]: np.std(win_rates) can exceed 1.0
    ✅ regime_consistency clamped [0, 1]: uses coefficient of variation
    ✅ All-wins / all-losses per window handled gracefully (PF capped)
    ✅ Minimum window count guard (≥ 2 for meaningful std)
    ✅ Breakeven trades (return == 0) handled explicitly
    ✅ Deterministic: no RNG involved
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

import numpy as np


# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_TRAIN_SIZE = 100
_DEFAULT_TEST_SIZE = 30
_DEFAULT_MIN_WINDOWS = 2
_DEFAULT_WIN_RATE_THRESHOLD = 0.55
_DEFAULT_PF_THRESHOLD = 1.4
_DEFAULT_STABILITY_THRESHOLD = 0.70
_PF_CAP = 100.0  # Cap infinite PF for averaging sanity


@dataclass(frozen=True)
class WalkForwardResult:
    """Immutable result of walk-forward out-of-sample validation."""

    avg_win_rate: float
    avg_profit_factor: float
    stability_score: float         # 0.0 = chaotic, 1.0 = perfectly stable
    regime_consistency: float      # 0.0 = regime-sensitive, 1.0 = regime-robust
    window_count: int
    per_window_win_rates: tuple[float, ...]
    per_window_profit_factors: tuple[float, ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L12 synthesis consumption."""
        return {
            "avg_win_rate": self.avg_win_rate,
            "avg_profit_factor": self.avg_profit_factor,
            "stability_score": self.stability_score,
            "regime_consistency": self.regime_consistency,
            "window_count": self.window_count,
            "per_window_win_rates": list(self.per_window_win_rates),
            "per_window_profit_factors": list(self.per_window_profit_factors),
            "passed": self.passed,
        }


class WalkForwardValidator:
    """Rolling walk-forward OOS validator.

    Slides ``train_size + test_size`` window across the return series,
    stepping by ``test_size``. Scores each OOS window independently.

    Parameters
    ----------
    train_size : int
        Returns in the training (in-sample) portion. Default 100.
    test_size : int
        Returns in the OOS (test) portion. Default 30.
    min_windows : int
        Minimum OOS windows required for valid result (≥ 2). Default 2.
    win_rate_threshold : float
        Minimum avg OOS win-rate to pass. Default 0.55.
    pf_threshold : float
        Minimum avg OOS profit factor to pass. Default 1.4.
    stability_threshold : float
        Minimum stability score to pass. Default 0.70.
    """

    def __init__(
        self,
        train_size: int = _DEFAULT_TRAIN_SIZE,
        test_size: int = _DEFAULT_TEST_SIZE,
        min_windows: int = _DEFAULT_MIN_WINDOWS,
        win_rate_threshold: float = _DEFAULT_WIN_RATE_THRESHOLD,
        pf_threshold: float = _DEFAULT_PF_THRESHOLD,
        stability_threshold: float = _DEFAULT_STABILITY_THRESHOLD,
    ) -> None:
        if train_size < 1:
            raise ValueError(f"train_size must be ≥ 1, got {train_size}")
        if test_size < 1:
            raise ValueError(f"test_size must be ≥ 1, got {test_size}")

        self._train_size = train_size
        self._test_size = test_size
        self._min_windows = max(2, min_windows)
        self._win_rate_threshold = win_rate_threshold
        self._pf_threshold = pf_threshold
        self._stability_threshold = stability_threshold

    # ── Public API ───────────────────────────────────────────────────────────

    def run(self, returns: List[float]) -> WalkForwardResult:
        """Run walk-forward OOS validation.

        Args:
            returns: Chronological per-trade P&L values.

        Returns:
            WalkForwardResult with stability and regime-consistency metrics.

        Raises:
            ValueError: If data insufficient for even one complete window.
        """
        min_for_one_window = self._train_size + self._test_size
        if len(returns) < min_for_one_window:
            raise ValueError(
                f"Insufficient data for walk-forward validation: "
                f"need ≥ {min_for_one_window}, got {len(returns)}"
            )

        arr = np.asarray(returns, dtype=np.float64)
        n = len(arr)

        win_rates: list[float] = []
        profit_factors: list[float] = []

        start = 0
        while start + self._train_size + self._test_size <= n:
            test_start = start + self._train_size
            test_end = test_start + self._test_size
            test = arr[test_start:test_end]

            wr, pf = self._score_window(test)
            win_rates.append(wr)
            profit_factors.append(pf)

            start += self._test_size

        window_count = len(win_rates)
        if window_count < self._min_windows:
            raise ValueError(
                f"Only {window_count} OOS windows produced, "
                f"need ≥ {self._min_windows}. Add more data or reduce window sizes."
            )

        wr_arr = np.array(win_rates, dtype=np.float64)
        pf_arr = np.array(profit_factors, dtype=np.float64)

        avg_win = float(np.mean(wr_arr))
        avg_pf = float(np.mean(pf_arr))

        stability = self._compute_stability(wr_arr)
        regime_consistency = self._compute_regime_consistency(pf_arr)

        passed = (
            avg_win >= self._win_rate_threshold
            and avg_pf >= self._pf_threshold
            and stability >= self._stability_threshold
        )

        return WalkForwardResult(
            avg_win_rate=round(avg_win, 4),
            avg_profit_factor=round(avg_pf, 2),
            stability_score=round(stability, 4),
            regime_consistency=round(regime_consistency, 4),
            window_count=window_count,
            per_window_win_rates=tuple(round(w, 4) for w in win_rates),
            per_window_profit_factors=tuple(round(p, 2) for p in profit_factors),
            passed=passed,
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _score_window(test: np.ndarray) -> tuple[float, float]:
        """Score a single OOS window.

        Returns (win_rate, profit_factor) with safe edge-case handling.
        """
        if len(test) == 0:
            return 0.0, 0.0

        wins = test[test > 0]
        losses = test[test < 0]
        # Breakeven (== 0) counted in denominator but neither win nor loss

        win_rate = float(len(wins) / len(test))

        gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
        gross_loss = float(np.abs(losses.sum())) if len(losses) > 0 else 0.0

        if gross_loss > 0.0:
            pf = gross_profit / gross_loss
        elif gross_profit > 0.0:
            # All wins, zero losses → perfect window, cap PF
            pf = _PF_CAP
        else:
            # No wins, no losses (all breakeven or empty) → neutral
            pf = 0.0

        return win_rate, min(pf, _PF_CAP)

    @staticmethod
    def _compute_stability(win_rates: np.ndarray) -> float:
        """Stability = 1 - std(win_rates), clamped to [0, 1].

        High std → low stability. Uses ddof=1 for sample std.
        """
        if len(win_rates) < 2:
            return 1.0
        std = float(np.std(win_rates, ddof=1))
        return max(0.0, min(1.0, 1.0 - std))

    @staticmethod
    def _compute_regime_consistency(profit_factors: np.ndarray) -> float:
        """Regime consistency = 1 - CV(profit_factors), clamped to [0, 1].

        Uses coefficient of variation (std/mean) so that regime consistency
        is scale-invariant across different profit-factor magnitudes.
        """
        if len(profit_factors) < 2:
            return 1.0
        mean_pf = float(np.mean(profit_factors))
        std_pf = float(np.std(profit_factors, ddof=1))
        cv = std_pf / mean_pf if mean_pf > 0.0 else std_pf
        return max(0.0, min(1.0, 1.0 - cv))
````

---

## 2. Regime Classifier ML

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\regime_classifier_ml.py
"""Regime Classifier — Hurst-exponent + volatility-based regime detection.

Statistical regime detection without hardcoded SMA thresholds:
    TRENDING       (H > 0.60)  — persistent price moves
    MEAN_REVERTING (H < 0.45)  — oscillatory / range-bound
    TRANSITION     (otherwise) — ambiguous / regime shift

Authority: ANALYSIS-ONLY. No execution side-effects.
           Enriches L1 Context as secondary confirmation.
           Does NOT replace L1 — acts as a parallel signal.

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
from typing import Any, List

import numpy as np


_MIN_PRICES = 25  # Hurst needs lag range(2, 20) + enough returns


@dataclass(frozen=True)
class RegimeClassification:
    """Immutable result of regime classification."""

    regime: str               # TRENDING | MEAN_REVERTING | TRANSITION
    confidence: float         # 0.0–1.0 (distance from random walk H=0.5)
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

    def classify(self, prices: List[float]) -> RegimeClassification:
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
            return 0.5  # Not enough data → assume random walk

        valid_lags: list[int] = []
        valid_tau: list[float] = []

        for lag in range(self._min_lag, effective_max):
            diff = ts[lag:] - ts[:-lag]
            if len(diff) < 2:
                continue
            std_val = float(np.std(diff, ddof=1))
            # FIX: Guard log(0) — skip lags with zero or negative std
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
````

---

## 3. Correlation Risk Engine

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\correlation_risk_engine.py
"""Correlation Risk Engine — Multi-pair hidden exposure detector.

Computes pairwise correlation across instruments to detect:
    - USD concentration risk (EURUSD + GBPUSD + XAUUSD overlap)
    - Multi-pair drawdown amplification
    - Hidden factor exposure via eigenvalue concentration

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds L6 Risk as portfolio-level adjustment.
           L6 is currently PLACEHOLDER — this fills that gap.

Bug fixes over original draft:
    ✅ Single-row matrix guard (need ≥ 2 pairs)
    ✅ NaN/Inf handling in return matrix (np.nan_to_num)
    ✅ Eigenvalue-based Herfindahl concentration (replaces max*avg product)
    ✅ Constant-series guard (NaN correlation → 0)
    ✅ Minimum observations guard
    ✅ High-correlation pair flagging with labels
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np


@dataclass(frozen=True)
class CorrelationRiskResult:
    """Immutable result of multi-pair correlation risk evaluation."""

    max_correlation: float
    average_correlation: float
    concentration_risk: float      # Eigenvalue-based [0, 1]
    num_pairs: int
    high_correlation_pairs: tuple[tuple[int, int, float], ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L6 risk consumption."""
        return {
            "max_correlation": self.max_correlation,
            "average_correlation": self.average_correlation,
            "concentration_risk": self.concentration_risk,
            "num_pairs": self.num_pairs,
            "high_correlation_pairs": [
                {"pair_i": i, "pair_j": j, "correlation": c}
                for i, j, c in self.high_correlation_pairs
            ],
            "passed": self.passed,
        }


class CorrelationRiskEngine:
    """Multi-pair correlation and concentration risk evaluator.

    Parameters
    ----------
    max_corr_threshold : float
        Maximum allowed |correlation| before failing. Default 0.85.
    high_corr_flag : float
        Threshold above which a pair is flagged. Default 0.70.
    min_observations : int
        Minimum return observations per pair. Default 20.
    """

    def __init__(
        self,
        max_corr_threshold: float = 0.85,
        high_corr_flag: float = 0.70,
        min_observations: int = 20,
    ) -> None:
        if max_corr_threshold <= 0 or max_corr_threshold > 1.0:
            raise ValueError(f"max_corr_threshold must be in (0, 1], got {max_corr_threshold}")
        self._max_corr = max_corr_threshold
        self._high_corr_flag = high_corr_flag
        self._min_obs = min_observations

    # ── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        return_matrix: List[List[float]] | np.ndarray,
        pair_labels: Optional[List[str]] = None,
    ) -> CorrelationRiskResult:
        """Evaluate correlation risk across multiple instruments.

        Args:
            return_matrix: 2D array of shape (num_pairs, num_observations).
                Each row = one instrument's return series.
            pair_labels: Optional names per row (for logging only).

        Returns:
            CorrelationRiskResult with concentration and pairwise metrics.

        Raises:
            ValueError: If fewer than 2 pairs or insufficient observations.
        """
        mat = np.asarray(return_matrix, dtype=np.float64)

        if mat.ndim != 2:
            raise ValueError(f"Expected 2D return matrix, got shape {mat.shape}")

        num_pairs, num_obs = mat.shape

        if num_pairs < 2:
            raise ValueError(
                f"Minimum 2 pairs required for correlation analysis, got {num_pairs}"
            )
        if num_obs < self._min_obs:
            raise ValueError(
                f"Minimum {self._min_obs} observations per pair, got {num_obs}"
            )

        # ── Clean NaN / Inf ──────────────────────────────────────────
        if np.any(~np.isfinite(mat)):
            mat = np.nan_to_num(mat, nan=0.0, posinf=0.0, neginf=0.0)

        # ── Correlation matrix ───────────────────────────────────────
        corr_matrix = np.corrcoef(mat)
        # Constant series → NaN correlations → replace with 0
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

        # ── Upper triangle (exclude diagonal) ────────────────────────
        upper_idx = np.triu_indices(num_pairs, k=1)
        upper_corrs = corr_matrix[upper_idx]
        abs_upper = np.abs(upper_corrs)

        max_corr = float(np.max(abs_upper)) if len(abs_upper) > 0 else 0.0
        avg_corr = float(np.mean(abs_upper)) if len(abs_upper) > 0 else 0.0

        # ── High-correlation pairs ───────────────────────────────────
        high_pairs: list[tuple[int, int, float]] = []
        for idx in range(len(upper_corrs)):
            if float(abs_upper[idx]) >= self._high_corr_flag:
                i = int(upper_idx[0][idx])
                j = int(upper_idx[1][idx])
                high_pairs.append((i, j, round(float(upper_corrs[idx]), 4)))

        # ── Eigenvalue concentration (Herfindahl-Hirschman) ──────────
        concentration = self._eigenvalue_concentration(corr_matrix, num_pairs)

        passed = max_corr < self._max_corr

        return CorrelationRiskResult(
            max_correlation=round(max_corr, 4),
            average_correlation=round(avg_corr, 4),
            concentration_risk=round(concentration, 4),
            num_pairs=num_pairs,
            high_correlation_pairs=tuple(high_pairs),
            passed=passed,
        )

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _eigenvalue
```


## License: GPL-2.0
https://github.com/Thiti-Dev/search-algs-demonstration-gui/blob/6c486c498f3e459ede1ecdf01e25c8a18a806a4c/main_gui.py

```


I'll implement all 4 production engines with the identified bug fixes, plus update `engines/__init__.py` and write comprehensive unit tests. Every file respects constitutional boundaries (analysis-only, no execution side-effects).

---

## 1. Walk-Forward Validation Engine

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\walk_forward_validation_engine.py
"""Walk-Forward Validation Engine — Out-of-Sample overfitting guard.

Slides a rolling train/test window across historical trade returns
to verify regime-robust, out-of-sample performance before deployment.

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds advisory metrics to L7/L12 — does NOT decide trades.

Bug fixes over original draft:
    ✅ ZeroDivisionError guard: empty losses list → safe PF computation
    ✅ stability_score clamped [0, 1]: np.std(win_rates) can exceed 1.0
    ✅ regime_consistency clamped [0, 1]: uses coefficient of variation
    ✅ All-wins / all-losses per window handled gracefully (PF capped)
    ✅ Minimum window count guard (≥ 2 for meaningful std)
    ✅ Breakeven trades (return == 0) handled explicitly
    ✅ Deterministic: no RNG involved
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

import numpy as np


# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_TRAIN_SIZE = 100
_DEFAULT_TEST_SIZE = 30
_DEFAULT_MIN_WINDOWS = 2
_DEFAULT_WIN_RATE_THRESHOLD = 0.55
_DEFAULT_PF_THRESHOLD = 1.4
_DEFAULT_STABILITY_THRESHOLD = 0.70
_PF_CAP = 100.0  # Cap infinite PF for averaging sanity


@dataclass(frozen=True)
class WalkForwardResult:
    """Immutable result of walk-forward out-of-sample validation."""

    avg_win_rate: float
    avg_profit_factor: float
    stability_score: float         # 0.0 = chaotic, 1.0 = perfectly stable
    regime_consistency: float      # 0.0 = regime-sensitive, 1.0 = regime-robust
    window_count: int
    per_window_win_rates: tuple[float, ...]
    per_window_profit_factors: tuple[float, ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L12 synthesis consumption."""
        return {
            "avg_win_rate": self.avg_win_rate,
            "avg_profit_factor": self.avg_profit_factor,
            "stability_score": self.stability_score,
            "regime_consistency": self.regime_consistency,
            "window_count": self.window_count,
            "per_window_win_rates": list(self.per_window_win_rates),
            "per_window_profit_factors": list(self.per_window_profit_factors),
            "passed": self.passed,
        }


class WalkForwardValidator:
    """Rolling walk-forward OOS validator.

    Slides ``train_size + test_size`` window across the return series,
    stepping by ``test_size``. Scores each OOS window independently.

    Parameters
    ----------
    train_size : int
        Returns in the training (in-sample) portion. Default 100.
    test_size : int
        Returns in the OOS (test) portion. Default 30.
    min_windows : int
        Minimum OOS windows required for valid result (≥ 2). Default 2.
    win_rate_threshold : float
        Minimum avg OOS win-rate to pass. Default 0.55.
    pf_threshold : float
        Minimum avg OOS profit factor to pass. Default 1.4.
    stability_threshold : float
        Minimum stability score to pass. Default 0.70.
    """

    def __init__(
        self,
        train_size: int = _DEFAULT_TRAIN_SIZE,
        test_size: int = _DEFAULT_TEST_SIZE,
        min_windows: int = _DEFAULT_MIN_WINDOWS,
        win_rate_threshold: float = _DEFAULT_WIN_RATE_THRESHOLD,
        pf_threshold: float = _DEFAULT_PF_THRESHOLD,
        stability_threshold: float = _DEFAULT_STABILITY_THRESHOLD,
    ) -> None:
        if train_size < 1:
            raise ValueError(f"train_size must be ≥ 1, got {train_size}")
        if test_size < 1:
            raise ValueError(f"test_size must be ≥ 1, got {test_size}")

        self._train_size = train_size
        self._test_size = test_size
        self._min_windows = max(2, min_windows)
        self._win_rate_threshold = win_rate_threshold
        self._pf_threshold = pf_threshold
        self._stability_threshold = stability_threshold

    # ── Public API ───────────────────────────────────────────────────────────

    def run(self, returns: List[float]) -> WalkForwardResult:
        """Run walk-forward OOS validation.

        Args:
            returns: Chronological per-trade P&L values.

        Returns:
            WalkForwardResult with stability and regime-consistency metrics.

        Raises:
            ValueError: If data insufficient for even one complete window.
        """
        min_for_one_window = self._train_size + self._test_size
        if len(returns) < min_for_one_window:
            raise ValueError(
                f"Insufficient data for walk-forward validation: "
                f"need ≥ {min_for_one_window}, got {len(returns)}"
            )

        arr = np.asarray(returns, dtype=np.float64)
        n = len(arr)

        win_rates: list[float] = []
        profit_factors: list[float] = []

        start = 0
        while start + self._train_size + self._test_size <= n:
            test_start = start + self._train_size
            test_end = test_start + self._test_size
            test = arr[test_start:test_end]

            wr, pf = self._score_window(test)
            win_rates.append(wr)
            profit_factors.append(pf)

            start += self._test_size

        window_count = len(win_rates)
        if window_count < self._min_windows:
            raise ValueError(
                f"Only {window_count} OOS windows produced, "
                f"need ≥ {self._min_windows}. Add more data or reduce window sizes."
            )

        wr_arr = np.array(win_rates, dtype=np.float64)
        pf_arr = np.array(profit_factors, dtype=np.float64)

        avg_win = float(np.mean(wr_arr))
        avg_pf = float(np.mean(pf_arr))

        stability = self._compute_stability(wr_arr)
        regime_consistency = self._compute_regime_consistency(pf_arr)

        passed = (
            avg_win >= self._win_rate_threshold
            and avg_pf >= self._pf_threshold
            and stability >= self._stability_threshold
        )

        return WalkForwardResult(
            avg_win_rate=round(avg_win, 4),
            avg_profit_factor=round(avg_pf, 2),
            stability_score=round(stability, 4),
            regime_consistency=round(regime_consistency, 4),
            window_count=window_count,
            per_window_win_rates=tuple(round(w, 4) for w in win_rates),
            per_window_profit_factors=tuple(round(p, 2) for p in profit_factors),
            passed=passed,
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _score_window(test: np.ndarray) -> tuple[float, float]:
        """Score a single OOS window.

        Returns (win_rate, profit_factor) with safe edge-case handling.
        """
        if len(test) == 0:
            return 0.0, 0.0

        wins = test[test > 0]
        losses = test[test < 0]
        # Breakeven (== 0) counted in denominator but neither win nor loss

        win_rate = float(len(wins) / len(test))

        gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
        gross_loss = float(np.abs(losses.sum())) if len(losses) > 0 else 0.0

        if gross_loss > 0.0:
            pf = gross_profit / gross_loss
        elif gross_profit > 0.0:
            # All wins, zero losses → perfect window, cap PF
            pf = _PF_CAP
        else:
            # No wins, no losses (all breakeven or empty) → neutral
            pf = 0.0

        return win_rate, min(pf, _PF_CAP)

    @staticmethod
    def _compute_stability(win_rates: np.ndarray) -> float:
        """Stability = 1 - std(win_rates), clamped to [0, 1].

        High std → low stability. Uses ddof=1 for sample std.
        """
        if len(win_rates) < 2:
            return 1.0
        std = float(np.std(win_rates, ddof=1))
        return max(0.0, min(1.0, 1.0 - std))

    @staticmethod
    def _compute_regime_consistency(profit_factors: np.ndarray) -> float:
        """Regime consistency = 1 - CV(profit_factors), clamped to [0, 1].

        Uses coefficient of variation (std/mean) so that regime consistency
        is scale-invariant across different profit-factor magnitudes.
        """
        if len(profit_factors) < 2:
            return 1.0
        mean_pf = float(np.mean(profit_factors))
        std_pf = float(np.std(profit_factors, ddof=1))
        cv = std_pf / mean_pf if mean_pf > 0.0 else std_pf
        return max(0.0, min(1.0, 1.0 - cv))
```

## 2. Regime Classifier ML

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\regime_classifier_ml.py
"""Regime Classifier — Hurst-exponent + volatility-based regime detection.

Statistical regime detection without hardcoded SMA thresholds:
    TRENDING       (H > 0.60)  — persistent price moves
    MEAN_REVERTING (H < 0.45)  — oscillatory / range-bound
    TRANSITION     (otherwise) — ambiguous / regime shift

Authority: ANALYSIS-ONLY. No execution side-effects.
           Enriches L1 Context as secondary confirmation.
           Does NOT replace L1 — acts as a parallel signal.

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
from typing import Any, List

import numpy as np


_MIN_PRICES = 25  # Hurst needs lag range(2, 20) + enough returns


@dataclass(frozen=True)
class RegimeClassification:
    """Immutable result of regime classification."""

    regime: str               # TRENDING | MEAN_REVERTING | TRANSITION
    confidence: float         # 0.0–1.0 (distance from random walk H=0.5)
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

    def classify(self, prices: List[float]) -> RegimeClassification:
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
            return 0.5  # Not enough data → assume random walk

        valid_lags: list[int] = []
        valid_tau: list[float] = []

        for lag in range(self._min_lag, effective_max):
            diff = ts[lag:] - ts[:-lag]
            if len(diff) < 2:
                continue
            std_val = float(np.std(diff, ddof=1))
            # FIX: Guard log(0) — skip lags with zero or negative std
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
``
## 3. Correlation Risk Engine

````python
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\engines\correlation_risk_engine.py
"""Correlation Risk Engine — Multi-pair hidden exposure detector.

Computes pairwise correlation across instruments to detect:
    - USD concentration risk (EURUSD + GBPUSD + XAUUSD overlap)
    - Multi-pair drawdown amplification
    - Hidden factor exposure via eigenvalue concentration

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds L6 Risk as portfolio-level adjustment.
           L6 is currently PLACEHOLDER — this fills that gap.

Bug fixes over original draft:
    ✅ Single-row matrix guard (need ≥ 2 pairs)
    ✅ NaN/Inf handling in return matrix (np.nan_to_num)
    ✅ Eigenvalue-based Herfindahl concentration (replaces max*avg product)
    ✅ Constant-series guard (NaN correlation → 0)
    ✅ Minimum observations guard
    ✅ High-correlation pair flagging with labels
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np


@dataclass(frozen=True)
class CorrelationRiskResult:
    """Immutable result of multi-pair correlation risk evaluation."""

    max_correlation: float
    average_correlation: float
    concentration_risk: float      # Eigenvalue-based [0, 1]
    num_pairs: int
    high_correlation_pairs: tuple[tuple[int, int, float], ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L6 risk consumption."""
        return {
            "max_correlation": self.max_correlation,
            "average_correlation": self.average_correlation,
            "concentration_risk": self.concentration_risk,
            "num_pairs": self.num_pairs,
            "high_correlation_pairs": [
                {"pair_i": i, "pair_j": j, "correlation": c}
                for i, j, c in self.high_correlation_pairs
            ],
            "passed": self.passed,
        }


class CorrelationRiskEngine:
    """Multi-pair correlation and concentration risk evaluator.

    Parameters
    ----------
    max_corr_threshold : float
        Maximum allowed |correlation| before failing. Default 0.85.
    high_corr_flag : float
        Threshold above which a pair is flagged. Default 0.70.
    min_observations : int
        Minimum return observations per pair. Default 20.
    """

    def __init__(
        self,
        max_corr_threshold: float = 0.85,
        high_corr_flag: float = 0.70,
        min_observations: int = 20,
    ) -> None:
        if max_corr_threshold <= 0 or max_corr_threshold > 1.0:
            raise ValueError(f"max_corr_threshold must be in (0, 1], got {max_corr_threshold}")
        self._max_corr = max_corr_threshold
        self._high_corr_flag = high_corr_flag
        self._min_obs = min_observations

    # ── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        return_matrix: List[List[float]] | np.ndarray,
        pair_labels: Optional[List[str]] = None,
    ) -> CorrelationRiskResult:
        """Evaluate correlation risk across multiple instruments.

        Args:
            return_matrix: 2D array of shape (num_pairs, num_observations).
                Each row = one instrument's return series.
            pair_labels: Optional names per row (for logging only).

        Returns:
            CorrelationRiskResult with concentration and pairwise metrics.

        Raises:
            ValueError: If fewer than 2 pairs or insufficient observations.
        """
        mat = np.asarray(return_matrix, dtype=np.float64)

        if mat.ndim != 2:
            raise ValueError(f"Expected 2D return matrix, got shape {mat.shape}")

        num_pairs, num_obs = mat.shape

        if num_pairs < 2:
            raise ValueError(
                f"Minimum 2 pairs required for correlation analysis, got {num_pairs}"
            )
        if num_obs < self._min_obs:
            raise ValueError(
                f"Minimum {self._min_obs} observations per pair, got {num_obs}"
            )

        # ── Clean NaN / Inf ──────────────────────────────────────────
        if np.any(~np.isfinite(mat)):
            mat = np.nan_to_num(mat, nan=0.0, posinf=0.0, neginf=0.0)

        # ── Correlation matrix ───────────────────────────────────────
        corr_matrix = np.corrcoef(mat)
        # Constant series → NaN correlations → replace with 0
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

        # ── Upper triangle (exclude diagonal) ────────────────────────
        upper_idx = np.triu_indices(num_pairs, k=1)
        upper_corrs = corr_matrix[upper_idx]
        abs_upper = np.abs(upper_corrs)

        max_corr = float(np.max(abs_upper)) if len(abs_upper) > 0 else 0.0
        avg_corr = float(np.mean(abs_upper)) if len(abs_upper) > 0 else 0.0

        # ── High-correlation pairs ───────────────────────────────────
        high_pairs: list[tuple[int, int, float]] = []
        for idx in range(len(upper_corrs)):
            if float(abs_upper[idx]) >= self._high_corr_flag:
                i = int(upper_idx[0][idx])
                j = int(upper_idx[1][idx])
                high_pairs.append((i, j, round(float(upper_corrs[idx]), 4)))

        # ── Eigenvalue concentration (Herfindahl-Hirschman) ──────────
        concentration = self._eigenvalue_concentration(corr_matrix, num_pairs)

        passed = max_corr < self._max_corr

        return CorrelationRiskResult(
            max_correlation=round(max_corr, 4),
            average_correlation=round(avg_corr, 4),
            concentration_risk=round(concentration, 4),
            num_pairs=num_pairs,
            high_correlation_pairs=tuple(high_pairs),
            passed=passed,
        )

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _eigenvalue
```

