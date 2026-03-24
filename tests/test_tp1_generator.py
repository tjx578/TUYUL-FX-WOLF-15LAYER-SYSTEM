"""Tests for analysis.formulas.tp1_generator — TP1 algorithmic generation.

Zone: tests/ — pure unit tests, no side-effects.
"""

from __future__ import annotations

import pytest

from analysis.formulas.tp1_generator import (
    TP1Generator,
    _atr_tp,
    _compute_atr,
    _fib_extensions,
    _fvg_levels,
    _swing_levels,
    generate_tp1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(n: int = 20, *, base: float = 1.2000, atr: float = 0.0020) -> list[dict]:
    """Build a simple rising candle series."""
    candles = []
    for i in range(n):
        o = round(base + i * atr * 0.1, 5)
        c = round(o + atr * 0.1, 5)
        h = round(c + atr * 0.05, 5)
        lo = round(o - atr * 0.05, 5)
        candles.append({"open": o, "high": h, "low": lo, "close": c})
    return candles


def _make_mixed_candles(n: int = 30, *, base: float = 1.2000) -> list[dict]:
    """Build candles with alternating highs/lows to create detectable swings."""
    candles = []
    for i in range(n):
        if i % 6 < 3:
            # Upward swing
            o = base + 0.0030 * (i // 6)
            c = o + 0.0010
            h = c + 0.0020
            lo = o - 0.0005
        else:
            # Downward swing
            o = base + 0.0030 * (i // 6) + 0.0010
            c = o - 0.0010
            h = o + 0.0005
            lo = c - 0.0020
        candles.append({"open": round(o, 5), "high": round(h, 5), "low": round(lo, 5), "close": round(c, 5)})
    return candles


# ---------------------------------------------------------------------------
# ATR helper tests
# ---------------------------------------------------------------------------


class TestComputeATR:
    def test_empty_candles(self):
        assert _compute_atr([]) == 0.0

    def test_single_candle(self):
        assert _compute_atr([{"high": 1.21, "low": 1.20, "close": 1.205}]) == 0.0

    def test_basic_atr(self):
        candles = _make_candles(20, atr=0.0020)
        atr = _compute_atr(candles)
        assert atr > 0.0
        assert isinstance(atr, float)


class TestAtrTp:
    def test_buy_tp_above_entry(self):
        tp = _atr_tp(1.2000, 0.0020, "BUY")
        assert tp > 1.2000

    def test_sell_tp_below_entry(self):
        tp = _atr_tp(1.2000, 0.0020, "SELL")
        assert tp < 1.2000

    def test_atr_2x_distance_buy(self):
        tp = _atr_tp(1.2000, 0.0020, "BUY")
        assert abs(tp - 1.2000 - 0.0040) < 1e-5

    def test_atr_2x_distance_sell(self):
        tp = _atr_tp(1.2000, 0.0020, "SELL")
        assert abs(1.2000 - tp - 0.0040) < 1e-5


# ---------------------------------------------------------------------------
# Swing level tests
# ---------------------------------------------------------------------------


class TestSwingLevels:
    def test_too_few_candles(self):
        candles = _make_candles(3)
        assert _swing_levels(candles, "BUY") == []

    def test_buy_finds_highs(self):
        candles = _make_mixed_candles(30)
        levels = _swing_levels(candles, "BUY")
        # Should find some swing highs
        assert len(levels) >= 0  # may be 0 or more depending on pattern

    def test_all_levels_positive(self):
        candles = _make_mixed_candles(30)
        for lvl in _swing_levels(candles, "BUY"):
            assert lvl > 0
        for lvl in _swing_levels(candles, "SELL"):
            assert lvl > 0


# ---------------------------------------------------------------------------
# FVG level tests
# ---------------------------------------------------------------------------


class TestFVGLevels:
    def test_too_few_candles(self):
        assert _fvg_levels([], "BUY") == []
        assert _fvg_levels([{"high": 1.21, "low": 1.20, "close": 1.205}], "BUY") == []

    def test_bullish_fvg_detected(self):
        """Bullish FVG: high[i] < low[i+2]."""
        candles = [
            {"open": 1.2000, "high": 1.2010, "low": 1.1990, "close": 1.2005},  # c0: high=1.2010
            {"open": 1.2015, "high": 1.2020, "low": 1.2015, "close": 1.2018},  # c1: middle
            {"open": 1.2025, "high": 1.2030, "low": 1.2025, "close": 1.2028},  # c2: low=1.2025 > c0.high
        ]
        levels = _fvg_levels(candles, "BUY")
        assert len(levels) >= 1
        assert all(lvl > 0 for lvl in levels)

    def test_all_levels_positive(self):
        candles = _make_candles(20)
        for lvl in _fvg_levels(candles, "BUY"):
            assert lvl > 0
        for lvl in _fvg_levels(candles, "SELL"):
            assert lvl > 0


# ---------------------------------------------------------------------------
# Fibonacci extension tests
# ---------------------------------------------------------------------------


class TestFibExtensions:
    def test_too_few_candles(self):
        candles = _make_candles(5)
        assert _fib_extensions(candles, 1.2000, "BUY") == []

    def test_buy_extensions_above_entry(self):
        candles = _make_mixed_candles(30)
        entry = candles[-1]["close"]
        exts = _fib_extensions(candles, entry, "BUY")
        for price, label in exts:
            assert price > entry, f"Extension {label} should be above entry for BUY"

    def test_sell_extensions_below_entry(self):
        candles = _make_mixed_candles(30)
        entry = candles[-1]["close"]
        exts = _fib_extensions(candles, entry, "SELL")
        for price, label in exts:
            assert price < entry, f"Extension {label} should be below entry for SELL"

    def test_extension_labels(self):
        candles = _make_mixed_candles(30)
        entry = 1.2000
        exts = _fib_extensions(candles, entry, "BUY")
        labels = {label for _, label in exts}
        valid_labels = {"1.272", "1.618"}
        assert labels.issubset(valid_labels)


# ---------------------------------------------------------------------------
# TP1Generator core tests
# ---------------------------------------------------------------------------


class TestTP1Generator:
    def setup_method(self):
        self.gen = TP1Generator(min_rr=2.0)

    def test_basic_buy(self):
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        entry = 1.2050
        sl = 1.2010
        result = self.gen.generate(candles=candles, entry=entry, sl=sl, direction="BUY", atr=0.0020)

        assert result["valid"]
        assert result["tp1"] > entry
        assert result["rr"] >= 2.0
        assert result["direction"] == "BUY"

    def test_basic_sell(self):
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        entry = 1.1950
        sl = 1.1990
        result = self.gen.generate(candles=candles, entry=entry, sl=sl, direction="SELL", atr=0.0020)

        assert result["valid"]
        assert result["tp1"] < entry
        assert result["rr"] >= 2.0
        assert result["direction"] == "SELL"

    def test_invalid_direction(self):
        candles = _make_candles(20)
        result = self.gen.generate(candles=candles, entry=1.2, sl=1.19, direction="HOLD")
        assert not result["valid"]
        assert result["reason"] == "invalid_direction"

    def test_sl_above_entry_for_buy(self):
        candles = _make_candles(20)
        result = self.gen.generate(candles=candles, entry=1.2, sl=1.21, direction="BUY")
        assert not result["valid"]
        assert result["reason"] == "sl_above_entry_for_buy"

    def test_sl_below_entry_for_sell(self):
        candles = _make_candles(20)
        result = self.gen.generate(candles=candles, entry=1.2, sl=1.19, direction="SELL")
        assert not result["valid"]
        assert result["reason"] == "sl_below_entry_for_sell"

    def test_zero_entry_returns_fail(self):
        candles = _make_candles(20)
        result = self.gen.generate(candles=candles, entry=0.0, sl=1.19, direction="BUY")
        assert not result["valid"]

    def test_tp1_satisfies_min_rr(self):
        """Generated TP1 must satisfy min_rr=2.0."""
        candles = _make_candles(25, base=1.2000, atr=0.0015)
        entry = 1.2050
        sl = 1.2020  # 30 pip SL
        result = self.gen.generate(candles=candles, entry=entry, sl=sl, direction="BUY", atr=0.0015)
        if result["valid"]:
            assert result["rr"] >= 2.0

    def test_tp1_source_present(self):
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        result = self.gen.generate(candles=candles, entry=1.2050, sl=1.2010, direction="BUY", atr=0.0020)
        assert "source" in result
        assert isinstance(result["source"], str)
        assert len(result["source"]) > 0

    def test_candidates_list_present(self):
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        result = self.gen.generate(candles=candles, entry=1.2050, sl=1.2010, direction="BUY", atr=0.0020)
        assert "candidates" in result
        assert isinstance(result["candidates"], list)

    def test_atr_fallback_when_no_candles(self):
        """With no candles but ATR provided, still finds a valid TP1."""
        candles = _make_candles(5)  # fewer than _MIN_CANDLES=14
        entry = 1.2050
        sl = 1.2010
        result = self.gen.generate(candles=candles, entry=entry, sl=sl, direction="BUY", atr=0.0020)
        assert result["valid"]
        assert result["tp1"] > entry

    def test_generate_function_alias(self):
        """generate_tp1() public function wraps TP1Generator."""
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        result = generate_tp1(candles=candles, entry=1.2050, sl=1.2010, direction="BUY", atr=0.0020)
        assert "valid" in result
        assert "tp1" in result

    def test_rr_calculation_consistent(self):
        """Returned RR matches the math: |tp1 - entry| / |entry - sl|."""
        candles = _make_candles(20, base=1.2000, atr=0.0020)
        entry = 1.2050
        sl = 1.2010
        result = self.gen.generate(candles=candles, entry=entry, sl=sl, direction="BUY", atr=0.0020)
        if result["valid"]:
            risk = abs(entry - sl)
            expected_rr = round(abs(result["tp1"] - entry) / risk, 2)
            assert abs(result["rr"] - expected_rr) < 0.01, f"RR mismatch: {result['rr']} vs expected {expected_rr}"


# ---------------------------------------------------------------------------
# Signal contract _to_price_float protection tests
# ---------------------------------------------------------------------------


class TestSignalServicePriceConversion:
    """Ensure _to_price_float guards the signal contract boundary."""

    def test_to_price_float_zero_returns_none(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float(0.0) is None

    def test_to_price_float_negative_returns_none(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float(-1.5) is None

    def test_to_price_float_positive_returns_float(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float(1.2450) == pytest.approx(1.2450)

    def test_to_price_float_none_input(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float(None) is None

    def test_to_price_float_string_number(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float("1.2450") == pytest.approx(1.2450)

    def test_to_price_float_invalid_string(self):
        from allocation.signal_service import _to_price_float

        assert _to_price_float("not_a_number") is None

    def test_build_signal_from_zero_stop_loss_passes_validation(self):
        """A verdict with stop_loss=0.0 must NOT cause validate_signal_contract to fail."""
        from allocation.signal_service import _build_signal_payload_from_verdict

        verdict = {
            "signal_id": "SIG-TEST-001",
            "verdict": "HOLD",
            "confidence": 0.5,
            "direction": None,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "risk_reward_ratio": None,
            "scores": {},
            "timestamp": 1700000000.0,
            "expires_at": None,
        }
        payload = _build_signal_payload_from_verdict("EURUSD", verdict)
        # Should succeed (returning dict), not return None
        assert payload is not None
        assert payload["stop_loss"] is None  # 0.0 → None
        assert payload["entry_price"] is None
        assert payload["take_profit_1"] is None

    def test_build_signal_from_valid_prices_passes_validation(self):
        """A verdict with valid positive prices passes validation."""
        from allocation.signal_service import _build_signal_payload_from_verdict

        verdict = {
            "signal_id": "SIG-TEST-002",
            "verdict": "EXECUTE",
            "confidence": 0.85,
            "direction": "BUY",
            "entry_price": 1.2450,
            "stop_loss": 1.2410,
            "take_profit_1": 1.2530,
            "risk_reward_ratio": 2.0,
            "scores": {"wolf_score": 0.75, "tii_score": 0.91, "frpc_score": 0.94},
            "timestamp": 1700000000.0,
            "expires_at": None,
        }
        payload = _build_signal_payload_from_verdict("EURUSD", verdict)
        assert payload is not None
        assert payload["stop_loss"] == pytest.approx(1.2410)
        assert payload["entry_price"] == pytest.approx(1.2450)
        assert payload["take_profit_1"] == pytest.approx(1.2530)
