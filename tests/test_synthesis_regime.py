"""
Regression tests for regime_type and atr_ratio propagation in build_l12_synthesis().

Verifies that the synthesis builder:
1. Detects volatility regime from L3 ATR data when available.
2. Includes regime_type and atr_ratio in the returned synthesis dict.
3. Falls back gracefully to NORMAL_VOL when ATR data is absent or zero.
"""
from __future__ import annotations

from typing import Any

import pytest

from pipeline.phases.synthesis import build_l12_synthesis


def _make_layer_results(
    atr: float = 0.0,
    atr_mean_20: float = 0.0,
    trend: str = "NEUTRAL",
) -> dict[str, Any]:
    """Build a minimal layer_results dict for synthesis testing."""
    return {
        "L1": {"valid": True, "regime": "TREND", "regime_confidence": 0.8, "dominant_force": "NEUTRAL", "csi": 0.7},
        "L2": {"reflex_coherence": 0.85, "conf12": 0.80, "frpc_energy": 0.75},
        "L3": {"trend": trend, "trq3d_energy": 0.72, "drift": 0.001, "atr": atr, "atr_mean_20": atr_mean_20},
        "L4": {
            "technical_score": 70,
            "wolf_30_point": {"total": 22, "f_score": 7, "t_score": 8, "fta_score": 0.72, "exec_score": 7},
        },
        "L5": {"current_drawdown": 2.0, "psychology_score": 75, "eaf_score": 0.8},
        "L6": {
            "propfirm_compliant": True,
            "current_drawdown": 2.0,
            "drawdown_level": "LEVEL_0",
            "risk_multiplier": 1.0,
            "risk_status": "ACCEPTABLE",
            "lrce": 0.0,
            "rolling_sharpe": 1.2,
            "kelly_adjusted": 0.15,
        },
        "L7": {
            "win_probability": 62.0,
            "mc_passed_threshold": True,
            "bayesian_posterior": 0.63,
            "risk_of_ruin": 0.05,
            "profit_factor": 1.6,
            "bayesian_ci_low": 0.55,
            "bayesian_ci_high": 0.71,
            "validation": "PASS",
        },
        "L8": {"tii_sym": 0.91, "integrity": 0.94, "twms_score": 0.88},
        "L9": {"dvg_confidence": 0.78, "liquidity_score": 0.72, "smart_money_signal": "BULLISH"},
        "L10": {"fta_score": 0.74, "fta_multiplier": 1.1, "final_lot_size": 0.02, "adjusted_risk_pct": 1.0},
        "L11": {"entry_price": 1.0850, "stop_loss": 1.0800, "take_profit_1": 1.0950, "rr": 2.0},
        "macro_vix_state": {"regime_state": 1, "risk_multiplier": 1.0},
    }


class TestSynthesisRegimePropagation:
    """Verify regime_type and atr_ratio are included in synthesis output."""

    def test_regime_type_present_in_synthesis(self) -> None:
        """synthesis dict always contains regime_type key."""
        layer_results = _make_layer_results()
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert "regime_type" in synthesis

    def test_atr_ratio_present_in_synthesis(self) -> None:
        """synthesis dict always contains atr_ratio key."""
        layer_results = _make_layer_results()
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert "atr_ratio" in synthesis

    def test_default_regime_normal_vol_when_no_atr(self) -> None:
        """When L3 has no ATR data, regime_type defaults to NORMAL_VOL."""
        layer_results = _make_layer_results(atr=0.0, atr_mean_20=0.0)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["regime_type"] == "NORMAL_VOL"

    def test_default_atr_ratio_one_when_no_atr(self) -> None:
        """When L3 has no ATR data, atr_ratio defaults to 1.0."""
        layer_results = _make_layer_results(atr=0.0, atr_mean_20=0.0)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["atr_ratio"] == pytest.approx(1.0)

    def test_low_vol_regime_detected_from_atr(self) -> None:
        """Low ATR expansion ratio < 0.85 produces LOW_VOL regime."""
        # atr_current / atr_mean_20 = 0.80 / 1.00 = 0.80 < 0.85 → LOW_VOL
        layer_results = _make_layer_results(atr=0.0008, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["regime_type"] == "LOW_VOL"
        assert synthesis["atr_ratio"] == pytest.approx(0.80)

    def test_normal_vol_regime_detected_from_atr(self) -> None:
        """ATR expansion ratio between 0.85 and 1.20 produces NORMAL_VOL."""
        # atr_current / atr_mean_20 = 1.00 / 1.00 = 1.00 → NORMAL_VOL
        layer_results = _make_layer_results(atr=0.0010, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["regime_type"] == "NORMAL_VOL"
        assert synthesis["atr_ratio"] == pytest.approx(1.0)

    def test_high_vol_regime_detected_from_atr(self) -> None:
        """ATR expansion ratio > 1.20 produces HIGH_VOL regime."""
        # atr_current / atr_mean_20 = 1.30 / 1.00 = 1.30 > 1.20 → HIGH_VOL
        layer_results = _make_layer_results(atr=0.0013, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["regime_type"] == "HIGH_VOL"
        assert synthesis["atr_ratio"] == pytest.approx(1.3)

    def test_regime_missing_from_l3_defaults_gracefully(self) -> None:
        """If L3 is absent, regime_type defaults to NORMAL_VOL without raising."""
        layer_results = _make_layer_results()
        del layer_results["L3"]
        layer_results["L3"] = {}  # empty L3

        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert synthesis["regime_type"] == "NORMAL_VOL"
        assert synthesis["atr_ratio"] == pytest.approx(1.0)

    def test_regime_type_is_string(self) -> None:
        """regime_type is always a string."""
        layer_results = _make_layer_results(atr=0.0013, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert isinstance(synthesis["regime_type"], str)

    def test_atr_ratio_is_float(self) -> None:
        """atr_ratio is always a float."""
        layer_results = _make_layer_results(atr=0.0013, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        assert isinstance(synthesis["atr_ratio"], float)

    def test_synthesis_still_has_all_required_fields(self) -> None:
        """Adding regime fields does not remove any existing required synthesis fields."""
        required = ("pair", "scores", "layers", "execution", "risk", "propfirm", "bias", "system")
        layer_results = _make_layer_results(atr=0.0010, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        for field in required:
            assert field in synthesis, f"Missing required synthesis field: {field}"

    def test_regime_type_roundtrips_into_verdict_engine(self) -> None:
        """regime_type produced by synthesis is consumable by generate_l12_verdict()."""
        from constitution.verdict_engine import generate_l12_verdict
        from context.live_context_bus import LiveContextBus

        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.085, "ask": 1.0852, "timestamp": 1700000000.0, "source": "t"})

        layer_results = _make_layer_results(atr=0.0013, atr_mean_20=0.0010)
        synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")

        # Verdict engine must accept the synthesis without error
        verdict = generate_l12_verdict(synthesis)
        assert "gates" in verdict
        assert verdict["gates"]["total"] == 10
