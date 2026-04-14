"""Tests for engines.relative_strength_engine — Relative Strength Engine."""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock

from engines.relative_strength_engine import (
    MAJOR_CURRENCIES,
    CurrencyStrengthResult,
    RelativeStrengthEngine,
    _decompose_pair,
    _weighted_roc,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_candles(closes: list[float]) -> list[dict[str, Any]]:
    """Build a minimal candle list from close prices."""
    return [{"close": c, "open": c, "high": c, "low": c} for c in closes]


def _make_context_bus(pair_candles: dict[str, list[dict[str, Any]]]) -> MagicMock:
    """Build a mock context bus that returns pre-set candle data per pair/tf."""
    bus = MagicMock()

    def _get_candles(symbol: str, tf: str, count: int | None = None) -> list[dict[str, Any]] | None:
        key = symbol.upper()
        data = pair_candles.get(key)
        if data is None:
            return None
        if count is not None:
            return data[-count:]
        return data

    bus.get_candle_history = MagicMock(side_effect=_get_candles)
    return bus


# ---------------------------------------------------------------------------
# Tests: _decompose_pair
# ---------------------------------------------------------------------------

class TestDecomposePair:
    def test_valid_major(self) -> None:
        assert _decompose_pair("EURUSD") == ("EUR", "USD")

    def test_valid_cross(self) -> None:
        assert _decompose_pair("NZDCAD") == ("NZD", "CAD")

    def test_with_slash(self) -> None:
        assert _decompose_pair("EUR/USD") == ("EUR", "USD")

    def test_lowercase(self) -> None:
        assert _decompose_pair("gbpjpy") == ("GBP", "JPY")

    def test_invalid_length(self) -> None:
        assert _decompose_pair("XAU") is None
        assert _decompose_pair("XAUUSD") is None  # XAU not in MAJOR_CURRENCIES

    def test_commodity_not_tracked(self) -> None:
        assert _decompose_pair("XAUUSD") is None

    def test_empty(self) -> None:
        assert _decompose_pair("") is None


# ---------------------------------------------------------------------------
# Tests: _weighted_roc
# ---------------------------------------------------------------------------

class TestWeightedRoc:
    def test_uptrend(self) -> None:
        """Steadily rising closes should produce positive ROC."""
        closes = [1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09, 1.10,
                  1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.20]
        roc = _weighted_roc(closes)
        assert roc > 0.0

    def test_downtrend(self) -> None:
        """Steadily falling closes should produce negative ROC."""
        closes = [1.20, 1.19, 1.18, 1.17, 1.16, 1.15, 1.14, 1.13, 1.12, 1.11, 1.10,
                  1.09, 1.08, 1.07, 1.06, 1.05, 1.04, 1.03, 1.02, 1.01, 1.00]
        roc = _weighted_roc(closes)
        assert roc < 0.0

    def test_flat(self) -> None:
        """Flat closes should produce zero ROC."""
        closes = [1.0] * 25
        roc = _weighted_roc(closes)
        assert roc == 0.0

    def test_insufficient_data(self) -> None:
        """Fewer than MIN_CANDLES should return 0."""
        roc = _weighted_roc([1.0, 1.01, 1.02])
        assert roc == 0.0

    def test_clamped_to_range(self) -> None:
        """Extreme moves are clamped to [-1, +1]."""
        closes = [0.01] * 10 + [100.0]  # 10000x jump
        roc = _weighted_roc(closes)
        assert -1.0 <= roc <= 1.0

    def test_zero_past_price(self) -> None:
        """If past price is 0, that window is skipped gracefully."""
        closes = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        roc = _weighted_roc(closes)
        assert math.isfinite(roc)


# ---------------------------------------------------------------------------
# Tests: RelativeStrengthEngine.analyze
# ---------------------------------------------------------------------------

class TestRelativeStrengthEngine:
    """Integration tests for the full engine."""

    def _build_trending_candles(self, start: float, pct_change: float, count: int = 25) -> list[dict[str, Any]]:
        """Build candles trending up (pct_change > 0) or down (pct_change < 0)."""
        step = start * pct_change / count
        closes = [start + step * i for i in range(count)]
        return _make_candles(closes)

    def test_nzd_strong_cad_weak(self) -> None:
        """When NZD pairs rise and CAD pairs fall, NZD should rank above CAD."""
        pair_candles: dict[str, list[dict[str, Any]]] = {}

        # NZD pairs trending up (NZD strengthening)
        for pair in ("NZDUSD", "NZDJPY", "NZDCHF", "NZDCAD"):
            pair_candles[pair] = self._build_trending_candles(1.0, 0.05)

        # CAD pairs trending down (CAD weakening)
        for pair in ("USDCAD",):
            pair_candles[pair] = self._build_trending_candles(1.35, 0.05)  # USD/CAD up = CAD weak
        for pair in ("CADJPY",):
            pair_candles[pair] = self._build_trending_candles(110.0, -0.05)  # CAD/JPY down = CAD weak

        # Provide some EUR/GBP data for context
        pair_candles["EURUSD"] = self._build_trending_candles(1.08, 0.01)
        pair_candles["GBPUSD"] = self._build_trending_candles(1.26, 0.005)

        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="NZDCAD")

        # NZD should rank above CAD
        nzd_rank = result.currency_ranks.index("NZD")
        cad_rank = result.currency_ranks.index("CAD")
        assert nzd_rank < cad_rank, f"NZD rank={nzd_rank}, CAD rank={cad_rank}"

        # Delta should be positive (base NZD > quote CAD)
        assert result.relative_strength_delta > 0.0

        # Alignment should be BUY or STRONG_BUY
        assert result.alignment in ("BUY", "STRONG_BUY")

    def test_eur_weak_usd_strong(self) -> None:
        """When EURUSD drops, EUR weakens and USD strengthens."""
        pair_candles: dict[str, list[dict[str, Any]]] = {}
        pair_candles["EURUSD"] = self._build_trending_candles(1.12, -0.08)
        pair_candles["EURGBP"] = self._build_trending_candles(0.87, -0.04)
        pair_candles["EURJPY"] = self._build_trending_candles(165.0, -0.06)
        pair_candles["GBPUSD"] = self._build_trending_candles(1.26, 0.01)
        pair_candles["USDJPY"] = self._build_trending_candles(155.0, 0.03)

        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="EURUSD")

        assert result.base_currency == "EUR"
        assert result.quote_currency == "USD"
        assert result.relative_strength_delta < 0.0
        assert result.alignment in ("SELL", "STRONG_SELL")

    def test_neutral_when_flat(self) -> None:
        """All flat pairs should yield NEUTRAL alignment."""
        pair_candles: dict[str, list[dict[str, Any]]] = {}
        for pair in ("EURUSD", "GBPUSD", "USDJPY", "EURGBP"):
            pair_candles[pair] = _make_candles([1.0] * 25)

        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="EURUSD")

        assert result.alignment == "NEUTRAL"
        assert abs(result.relative_strength_delta) < 0.01

    def test_no_context_bus(self) -> None:
        """Without a context bus, returns empty result with error."""
        rse = RelativeStrengthEngine()
        result = rse.analyze(context_bus=None, symbol="EURUSD")
        assert result.pairs_analyzed == 0
        assert len(result.errors) > 0
        assert result.confidence == 0.0

    def test_invalid_symbol(self) -> None:
        """Non-decomposable symbol returns error."""
        bus = _make_context_bus({})
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="XAUUSD")
        assert len(result.errors) > 0
        assert "Cannot decompose" in result.errors[0]

    def test_all_currencies_ranked(self) -> None:
        """Even with partial data, all 8 major currencies appear in scores."""
        pair_candles: dict[str, list[dict[str, Any]]] = {}
        pair_candles["EURUSD"] = self._build_trending_candles(1.08, 0.02)
        pair_candles["GBPUSD"] = self._build_trending_candles(1.26, -0.01)
        pair_candles["USDJPY"] = self._build_trending_candles(155.0, 0.03)
        pair_candles["AUDUSD"] = self._build_trending_candles(0.67, 0.01)

        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="EURUSD")

        for ccy in MAJOR_CURRENCIES:
            assert ccy in result.currency_scores

    def test_confidence_scales_with_data(self) -> None:
        """More pairs analyzed → higher confidence."""
        few_pairs = {
            "EURUSD": self._build_trending_candles(1.08, 0.02),
        }
        many_pairs = {
            pair: self._build_trending_candles(1.0, 0.01)
            for pair in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD",
                         "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
                         "AUDJPY", "NZDCAD", "CADJPY", "AUDNZD")
        }

        rse = RelativeStrengthEngine()
        result_few = rse.analyze(_make_context_bus(few_pairs), symbol="EURUSD")
        result_many = rse.analyze(_make_context_bus(many_pairs), symbol="EURUSD")

        assert result_many.confidence > result_few.confidence

    def test_engine_isolates_failures(self) -> None:
        """If one pair throws, the engine continues with other pairs."""
        bus = MagicMock()
        call_count = 0

        def _flaky_candles(symbol: str, tf: str, count: int | None = None) -> Any:
            nonlocal call_count
            call_count += 1
            if symbol == "EURUSD":
                raise RuntimeError("Redis timeout")
            if symbol == "GBPUSD":
                return _make_candles([1.26 + 0.001 * i for i in range(25)])
            return None

        bus.get_candle_history = MagicMock(side_effect=_flaky_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="GBPUSD")

        # Should not crash; GBPUSD data should still be processed
        assert result.pairs_analyzed >= 1
        assert any("EURUSD" in e for e in result.errors)

    def test_to_dict_keys(self) -> None:
        """CurrencyStrengthResult.to_dict() has all expected keys."""
        result = CurrencyStrengthResult()
        d = result.to_dict()
        expected_keys = {
            "currency_scores", "currency_ranks", "base_currency",
            "quote_currency", "base_strength", "quote_strength",
            "relative_strength_delta", "alignment", "confidence",
            "pairs_analyzed", "pairs_available", "errors",
        }
        assert set(d.keys()) == expected_keys

    def test_custom_pair_universe(self) -> None:
        """Engine can be configured with a smaller pair universe."""
        small_universe = ("EURUSD", "GBPUSD", "USDJPY")
        pair_candles = {
            pair: _make_candles([1.0 + 0.001 * i for i in range(25)])
            for pair in small_universe
        }
        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine(pair_universe=small_universe)
        result = rse.analyze(bus, symbol="EURUSD")

        assert result.pairs_analyzed == 3
        assert result.confidence > 0.0

    def test_normalization_bounds(self) -> None:
        """All currency scores should be in [-1.0, +1.0]."""
        pair_candles = {
            "EURUSD": self._build_trending_candles(1.08, 0.10),
            "GBPUSD": self._build_trending_candles(1.26, -0.15),
            "USDJPY": self._build_trending_candles(155.0, 0.20),
            "AUDUSD": self._build_trending_candles(0.67, -0.05),
            "NZDUSD": self._build_trending_candles(0.60, 0.08),
        }
        bus = _make_context_bus(pair_candles)
        rse = RelativeStrengthEngine()
        result = rse.analyze(bus, symbol="EURUSD")

        for ccy, score in result.currency_scores.items():
            assert -1.0 <= score <= 1.0, f"{ccy} score {score} out of bounds"
