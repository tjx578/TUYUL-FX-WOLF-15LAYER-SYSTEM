"""
Edge Validator - Statistical Edge Verification

No scipy dependency - uses math.comb for binomial PMF.

Implements:
- One-sided binomial test: H0: p <= 0.75 vs H1: p > 0.75
- Wilson score confidence interval
- Expected value with RR: EV = WR × RR - (1-WR)
- Minimum trades estimator for significance

Returns frozen EdgeValidationResult with to_dict().

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from engines.v11.config import get_v11


@dataclass(frozen=True)
class EdgeValidationResult:
    """Immutable result of edge validation."""
    
    has_edge: bool
    win_rate: float
    p_value: float
    confidence_interval: tuple[float, float]
    expected_value: float
    min_trades_needed: int
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON."""
        return {
            "has_edge": self.has_edge,
            "win_rate": self.win_rate,
            "p_value": self.p_value,
            "confidence_interval": list(self.confidence_interval),
            "expected_value": self.expected_value,
            "min_trades_needed": self.min_trades_needed,
        }


class EdgeValidator:
    """
    Statistical edge validator using binomial test.
    
    Parameters
    ----------
    min_win_rate : float
        Minimum win rate for significance (default from config)
    alpha : float
        Significance level (default from config)
    min_trades : int
        Minimum trades for reliability (default from config)
    wilson_confidence : float
        Wilson score confidence level (default from config)
    """
    
    def __init__(
        self,
        min_win_rate: float | None = None,
        alpha: float | None = None,
        min_trades: int | None = None,
        wilson_confidence: float | None = None,
    ) -> None:
        self._min_win_rate = min_win_rate or get_v11("edge_validation.min_win_rate", 0.75)
        self._alpha = alpha or get_v11("edge_validation.alpha", 0.05)
        self._min_trades = min_trades or get_v11("edge_validation.min_trades", 30)
        self._wilson_conf = wilson_confidence or get_v11("edge_validation.wilson_confidence", 0.95)
    
    def validate(
        self,
        n_wins: int,
        n_trades: int,
        avg_rr: float = 1.0,
    ) -> EdgeValidationResult:
        """
        Validate statistical edge using binomial test.
        
        Args:
            n_wins: Number of winning trades
            n_trades: Total number of trades
            avg_rr: Average risk-reward ratio
        
        Returns:
            EdgeValidationResult with significance test results
        """
        if n_trades == 0:
            return self._no_edge_result()
        
        # Compute win rate
        win_rate = n_wins / n_trades
        
        # Binomial test: H0: p <= min_win_rate vs H1: p > min_win_rate
        p_value = self._binomial_test(n_wins, n_trades, self._min_win_rate)
        
        # Wilson score confidence interval
        ci_lower, ci_upper = self._wilson_score_interval(n_wins, n_trades)
        
        # Expected value: EV = WR × RR - (1 - WR)
        expected_value = win_rate * avg_rr - (1 - win_rate)
        
        # Minimum trades needed for significance
        min_trades_needed = self._estimate_min_trades(self._min_win_rate, self._alpha)
        
        # Has edge if:
        # 1. p_value < alpha (significant)
        # 2. win_rate > min_win_rate
        # 3. n_trades >= min_trades
        # 4. expected_value > 0
        has_edge = (
            p_value < self._alpha and
            win_rate > self._min_win_rate and
            n_trades >= self._min_trades and
            expected_value > 0
        )
        
        return EdgeValidationResult(
            has_edge=has_edge,
            win_rate=win_rate,
            p_value=p_value,
            confidence_interval=(ci_lower, ci_upper),
            expected_value=expected_value,
            min_trades_needed=min_trades_needed,
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
            prob = binom_coeff * (p ** k) * ((1 - p) ** (n - k))
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
        
        # Z-score for confidence level
        z = self._z_score(self._wilson_conf)
        
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
        
        Uses heuristic: n >= (Z/2)^2 / (p * (1-p))
        """
        z = self._z_score(1 - alpha)
        
        if target_wr == 0 or target_wr == 1:
            return 100  # Default for edge cases
        
        n = ((z / 2) ** 2) / (target_wr * (1 - target_wr))
        
        return int(math.ceil(n))
    
    def _no_edge_result(self) -> EdgeValidationResult:
        """Return result indicating no edge."""
        return EdgeValidationResult(
            has_edge=False,
            win_rate=0.0,
            p_value=1.0,
            confidence_interval=(0.0, 0.0),
            expected_value=0.0,
            min_trades_needed=self._min_trades,
        )
