"""Walk-Forward Validation Engine -- Out-of-Sample overfitting guard.

Slides a rolling train/test window across historical trade returns
to verify regime-robust, out-of-sample performance before deployment.

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds advisory metrics to L7/L12 -- does NOT decide trades.

Bug fixes over original draft:
    ✅ ZeroDivisionError guard: empty losses list -> safe PF computation
    ✅ stability_score clamped [0, 1]: np.std(win_rates) can exceed 1.0
    ✅ regime_consistency clamped [0, 1]: uses coefficient of variation
    ✅ All-wins / all-losses per window handled gracefully (PF capped)
    ✅ Minimum window count guard (≥ 2 for meaningful std)
    ✅ Breakeven trades (return == 0) handled explicitly
    ✅ Deterministic: no RNG involved
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

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

    def run(self, returns: list[float]) -> WalkForwardResult:
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
            # All wins, zero losses -> perfect window, cap PF
            pf = _PF_CAP
        else:
            # No wins, no losses (all breakeven or empty) -> neutral
            pf = 0.0

        return win_rate, min(pf, _PF_CAP)

    @staticmethod
    def _compute_stability(win_rates: np.ndarray) -> float:
        """Stability = 1 - std(win_rates), clamped to [0, 1].

        High std -> low stability. Uses ddof=1 for sample std.
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
