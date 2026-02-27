"""
Edge Validator — Statistical Edge Validation
Wolf-15 Layer Analysis System

Validates that detected trading edges have statistical significance
using rolling performance tracking and hypothesis testing.

Pure analysis module (L1–L11). No execution side-effects.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class EdgeStatus(Enum):
    """Status of an edge after validation."""

    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class EdgeMetrics:
    """Statistical metrics for an edge."""

    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_rr_realized: float = 0.0
    sharpe_ratio: float = 0.0
    max_consecutive_losses: int = 0
    sample_size: int = 0
    p_value: float = 1.0
    z_score: float = 0.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)


@dataclass
class EdgeValidationResult:
    """Result of edge validation."""

    status: EdgeStatus = EdgeStatus.INSUFFICIENT_DATA
    metrics: EdgeMetrics = field(default_factory=EdgeMetrics)
    score: float = 0.0
    degradation_warnings: list[str] = field(default_factory=list) # pyright: ignore[reportUnknownVariableType]
    details: dict[str, Any] = field(default_factory=dict) # pyright: ignore[reportUnknownVariableType]


class EdgeValidator:
    """
    Validates statistical edge for trading setups.

    Tracks rolling performance of setup types and validates that
    their edge remains statistically significant using basic
    hypothesis testing (proportional z-test, profit factor, etc.).

    Analysis-only: produces validation results, no execution side-effects.
    """

    def __init__(
        self,
        min_sample_size: int = 30,
        min_win_rate: float = 0.45,
        min_profit_factor: float = 1.2,
        significance_level: float = 0.05,
        rolling_window: int = 100,
    ) -> None:
        """
        Initialize edge validator.

        Args:
            min_sample_size: Minimum trades before edge can be validated.
            min_win_rate: Minimum win rate threshold.
            min_profit_factor: Minimum profit factor threshold.
            significance_level: Statistical significance level (alpha).
            rolling_window: Rolling window size for metrics.
        """
        super().__init__()
        self.min_sample_size = min_sample_size
        self.min_win_rate = min_win_rate
        self.min_profit_factor = min_profit_factor
        self.significance_level = significance_level
        self.rolling_window = rolling_window

        # Storage for trade results by setup type
        self._results: dict[str, list[float]] = {}

    def record_result(self, setup_type: str, pnl: float) -> None:
        """
        Record a trade result for a setup type.

        Args:
            setup_type: Identifier for the setup type.
            pnl: Profit/loss in R-multiples (positive = win).
        """
        if setup_type not in self._results:
            self._results[setup_type] = []

        self._results[setup_type].append(pnl)

        # Trim to rolling window
        if len(self._results[setup_type]) > self.rolling_window:
            self._results[setup_type] = self._results[setup_type][
                -self.rolling_window :
            ]

    def validate_edge(self, setup_type: str) -> EdgeValidationResult:
        """
        Validate the statistical edge for a setup type.

        Args:
            setup_type: Identifier for the setup type.

        Returns:
            EdgeValidationResult with status, metrics, and score.
        """
        results = self._results.get(setup_type, [])

        if len(results) < self.min_sample_size:
            return EdgeValidationResult(
                status=EdgeStatus.INSUFFICIENT_DATA,
                metrics=EdgeMetrics(sample_size=len(results)),
                details={"needed": float(self.min_sample_size)},
            )

        metrics = self._compute_metrics(results)
        warnings: list[str] = []

        # Check win rate
        win_rate_valid = metrics.win_rate >= self.min_win_rate
        if not win_rate_valid:
            warnings.append(
                f"Win rate {metrics.win_rate:.1%} below threshold {self.min_win_rate:.1%}"
            )

        # Check profit factor
        pf_valid = metrics.profit_factor >= self.min_profit_factor
        if not pf_valid:
            warnings.append(
                f"Profit factor {metrics.profit_factor:.1f} below threshold {self.min_profit_factor:.1f}"
            )

        # Check for sufficient sample size
        if metrics.sample_size < self.min_sample_size:
            warnings.append(
                f"Sample size {metrics.sample_size} below minimum {self.min_sample_size}"
            )

        # Check for significant p-value
        if metrics.p_value < self.significance_level:
            warnings.append(
                f"P-value {metrics.p_value:.1f} below significance level {self.significance_level:.1f}"
            )

        # Has edge if:
        # 1. p_value < alpha (significant)
        # 2. win_rate > min_win_rate
        # 3. n_trades >= min_trades
        # 4. expected_value > 0
        has_edge = (
            metrics.p_value < self.significance_level and
            win_rate_valid and
            metrics.sample_size >= self.min_sample_size and
            metrics.profit_factor > 0
        )

        return EdgeValidationResult(
            status=EdgeStatus.VALID if has_edge else EdgeStatus.DEGRADED,
            metrics=metrics,
            score=metrics.profit_factor,
            degradation_warnings=warnings,
            details={k: v for k, v in metrics.__dict__.items()},  # ensure string keys
        )

    def _compute_metrics(self, results: list[float]) -> EdgeMetrics:
        """Compute statistical metrics for a list of results."""
        if not results:
            return EdgeMetrics()

        n_trades = len(results)
        n_wins = sum(1 for x in results if x > 0)

        # Win rate
        win_rate = n_wins / n_trades

        # Profit factor
        gross_profit = sum(x for x in results if x > 0)
        gross_loss = abs(sum(x for x in results if x <= 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Average RR realized
        avg_rr_realized = gross_profit / n_wins if n_wins > 0 else 0.0

        # Sharpe ratio
        arr = np.array(results)
        std = float(np.std(arr, ddof=1)) if n_trades > 1 else 0.0
        sharpe_ratio = float(np.mean(arr)) / std if std > 0 else 0.0

        # Max consecutive losses
        max_consecutive_losses = 0
        current_streak = 0
        for x in results:
            if x <= 0:
                current_streak += 1
                max_consecutive_losses = max(max_consecutive_losses, current_streak)
            else:
                current_streak = 0

        # Sample size
        sample_size = n_trades

        # Confidence level for Wilson interval (1 - significance_level)
        wilson_conf = 1 - self.significance_level

        # P-value
        p_value = self._binomial_test(n_wins, n_trades, self.min_win_rate)

        # Z-score
        z_score = self._z_score(wilson_conf)

        # Confidence interval
        ci_lower, ci_upper = self._wilson_score_interval(n_wins, n_trades)

        return EdgeMetrics(
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_rr_realized=avg_rr_realized,
            sharpe_ratio=sharpe_ratio,
            max_consecutive_losses=max_consecutive_losses,
            sample_size=sample_size,
            p_value=p_value,
            z_score=z_score,
            confidence_interval=(ci_lower, ci_upper),
        )

    def _binomial_test(self, k: int, n: int, p0: float) -> float:
        """
        One-sided binomial test.

        H0: p <= p0 vs H1: p > p0

        P-value = P(X >= k | p = p0) = sum_{i=k}^{n} C(n,i) * p0^i * (1-p0)^(n-i)

        Args:
            k: Number of successes
            n: Number of trials
            p0: Null hypothesis probability

        Returns:
            P-value
        """
        p_value = 0.0

        for i in range(k, n + 1):
            p_value += self._binomial_pmf(i, n, p0)

        return p_value

    def _binomial_pmf(self, k: int, n: int, p: float) -> float:
        """
        Binomial probability mass function.

        P(X = k) = C(n, k) * p^k * (1-p)^(n-k)

        Args:
            k: Number of successes
            n: Number of trials
            p: Success probability

        Returns:
            Probability
        """
        try:
            # Use math.comb for binomial coefficient (Python 3.8+)
            binom_coeff = math.comb(n, k)
            prob: float = binom_coeff * (p ** k) * ((1 - p) ** (n - k))
            return prob
        except Exception:
            return 0.0

    def _wilson_score_interval(self, k: int, n: int) -> tuple[float, float]:
        """
        Wilson score confidence interval for binomial proportion.
        More accurate than normal approximation for small n.

        Args:
            k: Number of successes
            n: Number of trials
            Returns:
            (lower_bound, upper_bound)
        """
        if n == 0:
            return (0.0, 0.0)

        p_hat = k / n

        # Z-score for confidence level (1 - significance_level)
        z = self._z_score(1 - self.significance_level)

        # Wilson score formula
        denominator = 1 + (z ** 2) / n
        center = p_hat + (z ** 2) / (2 * n)
        margin = z * math.sqrt((p_hat * (1 - p_hat) + (z ** 2) / (4 * n)) / n)

        lower = (center - margin) / denominator
        upper = (center + margin) / denominator

        return (max(0.0, lower), min(1.0, upper))

    def _z_score(self, confidence: float) -> float:
        """
        Approximate Z-score for confidence level.

        Uses lookup table for common confidence levels.
        """
        lookup = {
            0.90: 1.645,
            0.95: 1.960,
            0.99: 2.576,
        }

        return lookup.get(confidence, 1.960)  # Default to 95%

    def _estimate_min_trades(self, target_wr: float, alpha: float) -> int:
        """
        Estimate minimum number of trades needed for significance.

        Uses standard formula: n = (z^2 * p * (1-p)) / margin^2
        Assumes margin of error = 0.05 (5%)
        """
        z = self._z_score(1 - alpha)
        margin = 0.05  # 5% margin of error

        if target_wr == 0 or target_wr == 1:
            return 100  # Default for edge cases

        n = (z ** 2 * target_wr * (1 - target_wr)) / (margin ** 2)

        return int(math.ceil(n))  # noqa: F821

    def _no_edge_result(self) -> EdgeValidationResult:
        """Return result indicating no edge."""
        return EdgeValidationResult(
            status=EdgeStatus.INVALID,
            metrics=EdgeMetrics(),
            score=0.0,
            degradation_warnings=["No edge detected"],
            details={},
        )
