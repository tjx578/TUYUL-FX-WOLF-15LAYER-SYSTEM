"""Tests for legacy FTA normalization, engine, and contracts.

Validates:
- clamp/normalization functions edge cases
- compute_pair_fta formula correctness
- calibrated vs claimed score separation
- confidence_hint formula
- trade band classification
- AUDCAD reference case from WOLF ARSENAL v4.0
"""

from __future__ import annotations

import pytest

from analysis.legacy_fta.contracts import LegacyCurrencyScore
from analysis.legacy_fta.engine import compute_pair_fta, compute_pair_fta_from_dict
from analysis.legacy_fta.normalization import (
    clamp01,
    fta100_to_l4_subscore,
    fta100_to_l10_confidence,
    gap_points_to_norm,
    score10_to_norm,
    score50_to_norm,
    score100_to_norm,
)

# ═══════════════════════════════════════════════════════════════════
# §1  NORMALIZATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════


class TestClamp01:
    def test_within_range(self):
        assert clamp01(0.5) == 0.5

    def test_lower_bound(self):
        assert clamp01(-1.0) == 0.0

    def test_upper_bound(self):
        assert clamp01(2.0) == 1.0

    def test_exact_zero(self):
        assert clamp01(0.0) == 0.0

    def test_exact_one(self):
        assert clamp01(1.0) == 1.0


class TestScore10ToNorm:
    def test_midpoint(self):
        assert score10_to_norm(5.0) == pytest.approx(0.5)

    def test_max(self):
        assert score10_to_norm(10.0) == pytest.approx(1.0)

    def test_zero(self):
        assert score10_to_norm(0.0) == pytest.approx(0.0)

    def test_overflow_clamped(self):
        assert score10_to_norm(15.0) == pytest.approx(1.0)

    def test_negative_clamped(self):
        assert score10_to_norm(-5.0) == pytest.approx(0.0)


class TestScore50ToNorm:
    def test_full(self):
        assert score50_to_norm(50.0) == pytest.approx(1.0)

    def test_half(self):
        assert score50_to_norm(25.0) == pytest.approx(0.5)

    def test_aud_example(self):
        assert score50_to_norm(37.0) == pytest.approx(0.74)


class TestScore100ToNorm:
    def test_full(self):
        assert score100_to_norm(100.0) == pytest.approx(1.0)

    def test_tech_score(self):
        assert score100_to_norm(86.0) == pytest.approx(0.86)


class TestGapPointsToNorm:
    def test_positive_gap(self):
        assert gap_points_to_norm(19.0) == pytest.approx(19.0 / 30.0, abs=1e-4)

    def test_negative_gap_uses_abs(self):
        assert gap_points_to_norm(-19.0) == pytest.approx(19.0 / 30.0, abs=1e-4)

    def test_zero_gap(self):
        assert gap_points_to_norm(0.0) == pytest.approx(0.0)

    def test_max_gap_clamped(self):
        assert gap_points_to_norm(50.0, max_gap=30.0) == pytest.approx(1.0)

    def test_custom_max_gap(self):
        assert gap_points_to_norm(15.0, max_gap=15.0) == pytest.approx(1.0)

    def test_zero_max_gap_returns_zero(self):
        assert gap_points_to_norm(10.0, max_gap=0.0) == pytest.approx(0.0)


class TestFTA100Converters:
    def test_l4_subscore_full(self):
        assert fta100_to_l4_subscore(100.0) == pytest.approx(5.0)

    def test_l4_subscore_half(self):
        assert fta100_to_l4_subscore(50.0) == pytest.approx(2.5)

    def test_l10_confidence_full(self):
        assert fta100_to_l10_confidence(100.0) == pytest.approx(1.0)

    def test_l10_confidence_91_4(self):
        assert fta100_to_l10_confidence(91.4) == pytest.approx(0.914)


# ═══════════════════════════════════════════════════════════════════
# §2  ENGINE — compute_pair_fta
# ═══════════════════════════════════════════════════════════════════


def _make_aud() -> LegacyCurrencyScore:
    return LegacyCurrencyScore(
        currency="AUD",
        total_50=37.0,
        cb_10=7.0,
        econ_10=6.0,
        commodity_10=8.0,
        risk_10=7.0,
        techpos_10=9.0,
    )


def _make_cad() -> LegacyCurrencyScore:
    return LegacyCurrencyScore(
        currency="CAD",
        total_50=18.0,
        cb_10=4.0,
        econ_10=3.0,
        commodity_10=5.0,
        risk_10=3.0,
        techpos_10=3.0,
    )


class TestComputePairFTA:
    """AUDCAD reference case from WOLF ARSENAL v4.0 doc."""

    def test_audcad_direction(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4, 95.0)
        assert result.direction == "BUY"

    def test_audcad_gap_points(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4)
        assert result.pair_gap_points == pytest.approx(19.0)

    def test_audcad_gap_norm(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4)
        assert result.pair_gap_norm == pytest.approx(19.0 / 30.0, abs=1e-4)

    def test_audcad_fta_norm(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4)
        assert result.fta_norm == pytest.approx(0.914, abs=1e-4)

    def test_audcad_confidence_hint(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4)
        expected = 0.70 * 0.914 + 0.30 * (19.0 / 30.0)
        assert result.confidence_hint == pytest.approx(expected, abs=1e-4)

    def test_audcad_trade_band_high(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4)
        assert result.trade_band == "HIGH"

    def test_claimed_vs_calibrated(self):
        result = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4, 95.0)
        assert result.fundamental_score_claimed_100 == 95.0
        assert result.fundamental_score_calibrated_100 == pytest.approx((19.0 / 30.0) * 100.0, abs=0.01)

    def test_claimed_not_used_in_confidence(self):
        """claimed_100 must not affect confidence_hint computation."""
        r1 = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4, 95.0)
        r2 = compute_pair_fta("AUDCAD", _make_aud(), _make_cad(), 86.0, 91.4, None)
        assert r1.confidence_hint == r2.confidence_hint


class TestComputePairFTAEdge:
    def test_equal_scores_hold(self):
        eq = LegacyCurrencyScore("USD", 25.0, 5.0, 5.0, 5.0, 5.0, 5.0)
        result = compute_pair_fta("USDUSD", eq, eq, 50.0, 50.0)
        assert result.direction == "HOLD"
        assert result.pair_gap_points == 0.0

    def test_sell_direction(self):
        weak = LegacyCurrencyScore("JPY", 10.0, 2.0, 2.0, 2.0, 2.0, 2.0)
        strong = LegacyCurrencyScore("EUR", 40.0, 8.0, 8.0, 8.0, 8.0, 8.0)
        result = compute_pair_fta("JPYEUR", weak, strong, 70.0, 70.0)
        assert result.direction == "SELL"

    def test_zero_fta_none_band(self):
        z = LegacyCurrencyScore("X", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        result = compute_pair_fta("XX", z, z, 0.0, 0.0)
        assert result.trade_band == "NONE"
        assert result.confidence_hint == 0.0

    def test_max_gap_clamped(self):
        high = LegacyCurrencyScore("A", 50.0, 10.0, 10.0, 10.0, 10.0, 10.0)
        low = LegacyCurrencyScore("B", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        result = compute_pair_fta("AB", high, low, 100.0, 100.0)
        # gap = 50, max_gap = 30, so gap_norm clamped to 1.0
        assert result.pair_gap_norm == pytest.approx(1.0)
        assert result.confidence_hint <= 1.0


class TestComputePairFTAFromDict:
    def test_audcad_dict(self):
        data = {
            "pair": "AUDCAD",
            "base_currency": "AUD",
            "quote_currency": "CAD",
            "base_total_50": 37.0,
            "quote_total_50": 18.0,
            "technical_score_100": 86.0,
            "fta_score_100": 91.4,
            "claimed_100": 95.0,
        }
        result = compute_pair_fta_from_dict(data)
        assert result.pair == "AUDCAD"
        assert result.direction == "BUY"
        assert result.fundamental_score_claimed_100 == 95.0

    def test_missing_keys_default_zero(self):
        result = compute_pair_fta_from_dict({})
        assert result.pair == "UNKNOWN"
        assert result.confidence_hint == 0.0
        assert result.direction == "HOLD"
