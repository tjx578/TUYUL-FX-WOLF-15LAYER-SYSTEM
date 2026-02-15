"""Quantum Probability Engine -- Layer-6 probabilistic analysis.

Computes Bayesian probability estimates, pattern recognition confidence,
and statistical edge metrics for trade setups.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ProbabilityResult:
    """Output of the Quantum Probability Engine."""

    # Probability estimates
    bullish_probability: float = 0.5
    bearish_probability: float = 0.5
    neutral_probability: float = 0.0

    # Statistical edge
    statistical_edge: float = 0.0  # +ve = bullish edge, -ve = bearish edge
    edge_confidence: float = 0.0

    # Pattern recognition
    pattern_detected: str = "NONE"
    pattern_reliability: float = 0.0

    # Distribution metrics
    skewness: float = 0.0
    kurtosis: float = 0.0
    mean_return: float = 0.0
    std_return: float = 0.0

    # Bayesian
    prior_bias: str = "NEUTRAL"
    posterior_bias: str = "NEUTRAL"

    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_returns(closes: np.ndarray) -> np.ndarray:
    if len(closes) < 2:
        return np.array([])
    returns = np.diff(closes) / closes[:-1]
    return returns[np.isfinite(returns)]


def _bayesian_update(prior_bull: float, likelihood_bull: float, likelihood_bear: float) -> float:
    """Simple Bayesian update. Returns posterior bullish probability."""
    prior_bear = 1.0 - prior_bull
    evidence = likelihood_bull * prior_bull + likelihood_bear * prior_bear
    if evidence <= 0:
        return prior_bull
    return (likelihood_bull * prior_bull) / evidence


def _detect_candle_pattern(candles: list[dict[str, Any]]) -> tuple[str, float]:
    """Very simple candle pattern detection."""
    if len(candles) < 3:
        return "NONE", 0.0

    last = candles[-1]
    prev = candles[-2]

    o, h, l, c = last.get("open", 0), last.get("high", 0), last.get("low", 0), last.get("close", 0)  # noqa: E741
    po, _ph, _pl, pc = prev.get("open", 0), prev.get("high", 0), prev.get("low", 0), prev.get("close", 0)

    body = abs(c - o)
    full_range = h - l if h > l else 1e-10

    # Doji
    if body / full_range < 0.1:
        return "DOJI", 0.5

    # Engulfing
    if c > o and pc < po and c > po and o < pc:
        return "BULLISH_ENGULFING", 0.7
    if c < o and pc > po and c < po and o > pc:
        return "BEARISH_ENGULFING", 0.7

    # Hammer (bullish)
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    if lower_shadow > body * 2 and upper_shadow < body * 0.5:
        return "HAMMER", 0.6

    # Shooting star (bearish)
    if upper_shadow > body * 2 and lower_shadow < body * 0.5:
        return "SHOOTING_STAR", 0.6

    return "NONE", 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class QuantumProbabilityEngine:
    """Quantum Probability Engine -- statistical edge analysis.

    Parameters
    ----------
    lookback : int
        Number of bars for statistical analysis.
    prior_bullish : float
        Default Bayesian prior for bullish outcome.
    """

    def __init__(
        self,
        lookback: int = 100,
        prior_bullish: float = 0.5,
        **_extra: Any,
    ) -> None:
        self.lookback = lookback
        self.prior_bullish = prior_bullish

    def analyze(
        self,
        candles: dict[str, list[dict[str, Any]]],
        symbol: str = "",
    ) -> ProbabilityResult:
        if not candles:
            return ProbabilityResult(metadata={"symbol": symbol, "error": "no_candles"})

        primary_tf = self._select_primary(candles)
        tf_candles = candles[primary_tf]

        if len(tf_candles) < 20:
            return ProbabilityResult(metadata={"symbol": symbol, "error": "insufficient_candles"})

        closes = np.array([c.get("close", 0.0) for c in tf_candles], dtype=np.float64)
        returns = _compute_returns(closes)

        if len(returns) < 10:
            return ProbabilityResult(metadata={"symbol": symbol, "error": "insufficient_returns"})

        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))
        skew = float(self._skewness(returns))
        kurt = float(self._kurtosis(returns))

        # Win rate (positive returns)
        win_count = int(np.sum(returns > 0))
        total = len(returns)
        empirical_bull = win_count / total

        # Bayesian update with empirical evidence
        likelihood_bull = empirical_bull
        likelihood_bear = 1.0 - empirical_bull
        posterior_bull = _bayesian_update(self.prior_bullish, likelihood_bull, likelihood_bear)

        # Statistical edge
        avg_win = float(np.mean(returns[returns > 0])) if win_count > 0 else 0.0
        avg_loss = float(np.mean(returns[returns <= 0])) if (total - win_count) > 0 else 0.0
        edge = empirical_bull * avg_win + (1 - empirical_bull) * avg_loss

        # Pattern detection
        pattern, pattern_reliability = _detect_candle_pattern(tf_candles)

        # Edge confidence
        edge_conf = min(1.0, total / self.lookback * 0.5 + abs(edge) / (std_ret + 1e-8) * 0.5)

        # Classify biases
        prior_bias = "NEUTRAL"
        posterior_bias = "NEUTRAL"
        if posterior_bull > 0.55:
            posterior_bias = "BULLISH"
        elif posterior_bull < 0.45:
            posterior_bias = "BEARISH"

        confidence = min(1.0, 0.3 + (total / 100) * 0.3 + edge_conf * 0.4)

        return ProbabilityResult(
            bullish_probability=round(posterior_bull, 4),
            bearish_probability=round(1.0 - posterior_bull, 4),
            neutral_probability=round(max(0, 1.0 - abs(posterior_bull - 0.5) * 4), 4),
            statistical_edge=round(edge * 10000, 2),  # in basis points
            edge_confidence=round(edge_conf, 3),
            pattern_detected=pattern,
            pattern_reliability=round(pattern_reliability, 3),
            skewness=round(skew, 4),
            kurtosis=round(kurt, 4),
            mean_return=round(mean_ret * 10000, 4),  # bps
            std_return=round(std_ret * 10000, 4),     # bps
            prior_bias=prior_bias,
            posterior_bias=posterior_bias,
            confidence=round(confidence, 3),
            metadata={"symbol": symbol, "primary_tf": primary_tf, "sample_size": total},
        )

    @staticmethod
    def _skewness(data: np.ndarray) -> float:
        n = len(data)
        if n < 3:
            return 0.0
        m = np.mean(data)
        s = np.std(data)
        if s == 0:
            return 0.0
        return float(np.mean(((data - m) / s) ** 3))

    @staticmethod
    def _kurtosis(data: np.ndarray) -> float:
        n = len(data)
        if n < 4:
            return 0.0
        m = np.mean(data)
        s = np.std(data)
        if s == 0:
            return 0.0
        return float(np.mean(((data - m) / s) ** 4)) - 3.0

    @staticmethod
    def _select_primary(candles: dict[str, list[dict[str, Any]]]) -> str:
        for tf in ["M15", "H1", "H4"]:
            if tf in candles and len(candles[tf]) >= 20:
                return tf
        return max(candles, key=lambda k: len(candles[k]))
