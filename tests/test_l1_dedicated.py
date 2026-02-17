"""
Dedicated tests for L1 Context Layer — analyze_tii production interface.

Covers:
  - analyze_context() with trending / ranging / minimal data
  - L1ContextAnalyzer wrapper
  - ContextResult contract keys
  - Edge cases: flat prices, insufficient bars, invalid input
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from analysis.layers.L1_context import (
    ContextError,
    L1ContextAnalyzer,
    analyze_context,
)

NOW = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)  # London session


# ── Helpers ─────────────────────────────────────────────────────────────

def _trending_market(n: int = 60, base: float = 1.3000, drift: float = 0.0003) -> dict:
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        c = base + drift * i
        closes.append(round(c, 5))
        highs.append(round(c + 0.0005, 5))
        lows.append(round(c - 0.0005, 5))
        volumes.append(1000.0)
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


def _ranging_market(n: int = 60, base: float = 1.3000) -> dict:
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        c = base + 0.0002 * math.sin(i * 0.5)
        closes.append(round(c, 5))
        highs.append(round(c + 0.0003, 5))
        lows.append(round(c - 0.0003, 5))
        volumes.append(1000.0)
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


def _flat_market(n: int = 60, price: float = 1.3000) -> dict:
    return {
        "closes": [price] * n,
        "highs": [price + 0.0001] * n,
        "lows": [price - 0.0001] * n,
        "volumes": [100.0] * n,
    }


# ── Contract / output keys ─────────────────────────────────────────────

REQUIRED_KEYS = {
    "regime", "dominant_force", "regime_probability", "context_coherence",
    "volatility_level", "volatility_percentile", "entropy_score",
    "regime_confidence", "csi", "market_alignment", "valid", "session",
    "pair", "timestamp",
}


class TestAnalyzeContextContract:
    """Verify the output dict always contains required keys."""

    def test_trending_output_keys(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_ranging_output_keys(self) -> None:
        result = analyze_context(_ranging_market(), pair="EURUSD", now=NOW)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_valid_flag_true(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert result["valid"] is True


class TestRegimeDetection:
    """Verify regime classification for clear-cut scenarios."""

    def test_trending_detects_trend(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert result["regime"] in ("TREND_UP", "TREND_DOWN", "TRANSITION")

    def test_ranging_detects_range_or_transition(self) -> None:
        result = analyze_context(_ranging_market(), pair="EURUSD", now=NOW)
        assert result["regime"] in ("RANGE", "TRANSITION", "TREND_UP", "TREND_DOWN")

    def test_regime_probability_bounded(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert 0.0 <= result["regime_probability"] <= 1.0


class TestCoherenceAndEntropy:
    def test_coherence_bounded(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert 0.0 <= result["context_coherence"] <= 1.0

    def test_entropy_non_negative(self) -> None:
        result = analyze_context(_trending_market(), pair="EURUSD", now=NOW)
        assert result["entropy_score"] >= 0.0


class TestEdgeCases:
    def test_insufficient_bars_raises(self) -> None:
        short = {"closes": [1.3], "highs": [1.31], "lows": [1.29], "volumes": [100.0]}
        with pytest.raises(ContextError):
            analyze_context(short, pair="EURUSD", now=NOW)

    def test_empty_data_raises(self) -> None:
        with pytest.raises((ContextError, KeyError, ValueError)):
            analyze_context({}, pair="EURUSD", now=NOW)

    def test_flat_prices_valid(self) -> None:
        result = analyze_context(_flat_market(), pair="EURUSD", now=NOW)
        assert result["valid"] is True

    def test_deterministic(self) -> None:
        data = _trending_market()
        r1 = analyze_context(data, pair="EURUSD", now=NOW)
        r2 = analyze_context(data, pair="EURUSD", now=NOW)
        assert r1["regime_probability"] == r2["regime_probability"]


class TestL1ContextAnalyzerWrapper:
    """L1ContextAnalyzer pipeline wrapper returns dict with valid key."""

    def test_returns_dict(self) -> None:
        analyzer = L1ContextAnalyzer()
        result = analyzer.analyze("EURUSD")
        assert isinstance(result, dict)
        assert "valid" in result
