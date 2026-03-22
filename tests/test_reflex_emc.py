"""Tests for EMC Filter + Adaptive Sigma (analysis/reflex_emc.py)."""

from __future__ import annotations

import math

import pytest

from analysis.reflex_emc import EMCFilter

# ── Construction ──────────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_params(self) -> None:
        emc = EMCFilter()
        assert emc.decay == 0.8
        assert emc.sigma_base == 60.0

    def test_custom_params(self) -> None:
        emc = EMCFilter(decay=0.7, sigma_base=45.0)
        assert emc.decay == 0.7
        assert emc.sigma_base == 45.0

    def test_invalid_decay_zero(self) -> None:
        with pytest.raises(ValueError, match="decay"):
            EMCFilter(decay=0.0)

    def test_invalid_decay_one(self) -> None:
        with pytest.raises(ValueError, match="decay"):
            EMCFilter(decay=1.0)

    def test_invalid_decay_negative(self) -> None:
        with pytest.raises(ValueError, match="decay"):
            EMCFilter(decay=-0.5)


# ── Adaptive sigma ────────────────────────────────────────────────────────────


class TestAdaptiveSigma:
    def test_no_stress(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        # emotion_delta=0 → σ = 60 * 1.0 = 60
        assert math.isclose(emc.adaptive_sigma(0.0), 60.0)

    def test_moderate_stress(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        # emotion_delta=0.5 → σ = 60 * 1.5 = 90
        assert math.isclose(emc.adaptive_sigma(0.5), 90.0)

    def test_high_stress(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        # emotion_delta=1.0 → σ = 60 * 2.0 = 120
        assert math.isclose(emc.adaptive_sigma(1.0), 120.0)

    def test_small_emotion(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        # emotion_delta=0.1 → σ = 60 * 1.1 = 66
        assert math.isclose(emc.adaptive_sigma(0.1), 66.0)

    def test_clamps_negative_emotion(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        assert math.isclose(emc.adaptive_sigma(-0.5), 60.0)  # clamped to 0

    def test_clamps_above_one(self) -> None:
        emc = EMCFilter(sigma_base=60.0)
        assert math.isclose(emc.adaptive_sigma(1.5), 120.0)  # clamped to 1.0


# ── EMC smoothing ─────────────────────────────────────────────────────────────


class TestSmoothing:
    def test_first_value_is_raw(self) -> None:
        emc = EMCFilter(decay=0.8)
        result = emc.smooth("XAUUSD", 0.92)
        assert math.isclose(result, 0.92)

    def test_smoothing_dampens_crash(self) -> None:
        """A crash from 0.92 to 0.35 should be dampened, not direct LOCK."""
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.92)  # init
        smoothed = emc.smooth("XAUUSD", 0.35)  # crash
        # 0.8 * 0.92 + 0.2 * 0.35 = 0.736 + 0.07 = 0.806
        assert math.isclose(smoothed, 0.806, rel_tol=1e-6)

    def test_smoothing_gradual_recovery(self) -> None:
        """Recovery from a dip should be gradual, not instant."""
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.92)
        emc.smooth("XAUUSD", 0.35)  # crash → ~0.806
        s3 = emc.smooth("XAUUSD", 0.90)
        # 0.8 * 0.806 + 0.2 * 0.90 = 0.6448 + 0.18 = 0.8248
        assert math.isclose(s3, 0.8248, rel_tol=1e-4)
        # Still below OPEN threshold (0.85)
        assert s3 < 0.85

    def test_full_recovery_sequence(self) -> None:
        """Verify the user's spec: 5-cycle recovery from crash."""
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.92)  # cycle 1
        emc.smooth("XAUUSD", 0.35)  # cycle 2: crash
        emc.smooth("XAUUSD", 0.90)  # cycle 3
        emc.smooth("XAUUSD", 0.91)  # cycle 4
        s5 = emc.smooth("XAUUSD", 0.92)  # cycle 5
        # Should be approaching but may not yet fully reach 0.85
        assert s5 > 0.82

    def test_sustained_degradation_reaches_lock(self) -> None:
        """Sustained low values should eventually trigger LOCK territory."""
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.90)
        # Feed consistently low values
        result = 0.0
        for _ in range(20):
            result = emc.smooth("XAUUSD", 0.30)
        # After 20 cycles of 0.30, should converge near 0.30
        assert result < 0.40

    def test_clamps_output(self) -> None:
        emc = EMCFilter(decay=0.8)
        result = emc.smooth("XAUUSD", 1.5)
        assert 0.0 <= result <= 1.0

    def test_clamps_negative_input(self) -> None:
        emc = EMCFilter(decay=0.8)
        result = emc.smooth("XAUUSD", -0.5)
        assert 0.0 <= result <= 1.0


# ── Per-symbol isolation ──────────────────────────────────────────────────────


class TestSymbolIsolation:
    def test_symbols_independent(self) -> None:
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.90)
        emc.smooth("EURUSD", 0.40)
        # XAUUSD should still be at 0.90, not affected by EURUSD
        s_xau = emc.smooth("XAUUSD", 0.90)
        s_eur = emc.smooth("EURUSD", 0.40)
        assert s_xau > 0.85
        assert s_eur < 0.50

    def test_reset_single_symbol(self) -> None:
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.90)
        emc.smooth("EURUSD", 0.70)
        emc.reset("XAUUSD")
        assert not emc.get_session("XAUUSD")["exists"]
        assert emc.get_session("EURUSD")["exists"]

    def test_reset_all(self) -> None:
        emc = EMCFilter(decay=0.8)
        emc.smooth("XAUUSD", 0.90)
        emc.smooth("EURUSD", 0.70)
        emc.reset_all()
        assert not emc.get_session("XAUUSD")["exists"]
        assert not emc.get_session("EURUSD")["exists"]


# ── Session diagnostics ──────────────────────────────────────────────────────


class TestSessionDiagnostics:
    def test_nonexistent_symbol(self) -> None:
        emc = EMCFilter()
        info = emc.get_session("NOPE")
        assert not info["exists"]

    def test_session_tracks_cycles(self) -> None:
        emc = EMCFilter()
        emc.smooth("XAUUSD", 0.80)
        emc.smooth("XAUUSD", 0.75)
        emc.smooth("XAUUSD", 0.70)
        info = emc.get_session("XAUUSD")
        assert info["exists"]
        assert info["cycle_count"] == 3
        assert info["history_len"] == 3
