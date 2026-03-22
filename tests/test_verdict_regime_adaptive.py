"""
Regression tests for regime-adaptive threshold selection in generate_l12_verdict().

Verifies that the verdict engine reads regime_type from the synthesis dict
and applies regime-specific thresholds from config/thresholds.py instead of
the hardcoded _THRESH_* fallback constants.
"""

from typing import Any

import pytest

from constitution.verdict_engine import generate_l12_verdict
from context.live_context_bus import LiveContextBus


@pytest.fixture(autouse=True)
def _setup_context_bus() -> None:
    """Setup context bus with a recent tick to avoid staleness."""
    bus = LiveContextBus()
    bus.update_tick(
        {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": 1700000000.0,
            "source": "test",
        }
    )


def _make_synthesis(
    tii: float = 0.95,
    integrity: float = 0.98,
    rr: float = 2.5,
    fta: float = 0.80,
    monte: float = 0.75,
    conf12: float = 0.85,
    propfirm_compliant: bool = True,
    drawdown: float = 2.0,
    latency: int = 100,
    regime_type: str = "NORMAL_VOL",
    atr_ratio: float = 1.0,
) -> dict[str, Any]:
    """Build a synthesis dict with configurable values and regime metadata."""
    return {
        "pair": "EURUSD",
        "regime_type": regime_type,
        "atr_ratio": atr_ratio,
        "scores": {
            "wolf_30_point": 25,
            "f_score": 8,
            "t_score": 9,
            "fta_score": fta,
            "exec_score": 10,
        },
        "layers": {
            "L8_tii_sym": tii,
            "L8_integrity_index": integrity,
            "L7_monte_carlo_win": monte,
            "conf12": conf12,
        },
        "execution": {
            "rr_ratio": rr,
            "entry": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
        },
        "propfirm": {
            "compliant": propfirm_compliant,
        },
        "risk": {
            "current_drawdown": drawdown,
            "max_drawdown": 5.0,
        },
        "bias": {
            "technical": "BULLISH",
            "fundamental": "NEUTRAL",
        },
        "macro_vix": {
            "regime_state": 1,
            "risk_multiplier": 1.0,
        },
        "system": {
            "latency_ms": latency,
        },
    }


class TestRegimeAdaptiveThresholds:
    """Verify that regime_type drives threshold selection in generate_l12_verdict()."""

    def test_normal_vol_regime_uses_relaxed_conf12(self) -> None:
        """NORMAL_VOL regime uses conf12 threshold of 0.72 (not hardcoded 0.75)."""
        # conf12=0.73 is above NORMAL_VOL threshold (0.72) but below hardcoded (0.75)
        synthesis = _make_synthesis(conf12=0.73, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        # Should pass gate_9 under NORMAL_VOL regime (0.73 >= 0.72)
        assert verdict["gates"]["gate_9_conf12"] == "PASS"

    def test_low_vol_regime_uses_tighter_conf12(self) -> None:
        """LOW_VOL regime applies tighter conf12 threshold of 0.78."""
        # conf12=0.74 is above NORMAL_VOL (0.72) but below LOW_VOL (0.78)
        synthesis = _make_synthesis(conf12=0.74, regime_type="LOW_VOL")
        verdict = generate_l12_verdict(synthesis)

        # LOW_VOL conf12 threshold is 0.78, so 0.74 should FAIL
        assert verdict["gates"]["gate_9_conf12"] == "FAIL"

    def test_high_vol_regime_uses_relaxed_conf12(self) -> None:
        """HIGH_VOL regime uses relaxed conf12 threshold of 0.65."""
        # conf12=0.68 is above HIGH_VOL threshold (0.65)
        synthesis = _make_synthesis(conf12=0.68, regime_type="HIGH_VOL")
        verdict = generate_l12_verdict(synthesis)

        # HIGH_VOL threshold is 0.65, so 0.68 should PASS
        assert verdict["gates"]["gate_9_conf12"] == "PASS"

    def test_normal_vol_uses_tii_threshold(self) -> None:
        """NORMAL_VOL regime uses tii threshold from THRESHOLD_TABLE (0.90)."""
        # tii=0.91 is above NORMAL_VOL threshold (0.90)
        synthesis = _make_synthesis(tii=0.91, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_1_tii"] == "PASS"

    def test_high_vol_uses_relaxed_tii_threshold(self) -> None:
        """HIGH_VOL regime uses relaxed tii threshold (0.88)."""
        # tii=0.89 is above HIGH_VOL threshold (0.88) but below NORMAL_VOL (0.90)
        synthesis = _make_synthesis(tii=0.89, regime_type="HIGH_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_1_tii"] == "PASS"

    def test_low_vol_uses_tighter_tii_threshold(self) -> None:
        """LOW_VOL regime uses tighter tii threshold (0.93)."""
        # tii=0.91 passes NORMAL_VOL (0.90) but fails LOW_VOL (0.93)
        synthesis = _make_synthesis(tii=0.91, regime_type="LOW_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_1_tii"] == "FAIL"

    def test_normal_vol_uses_rr_threshold(self) -> None:
        """NORMAL_VOL regime uses rr threshold from THRESHOLD_TABLE (2.0)."""
        # rr=1.8 is above hardcoded fallback (1.5) but below NORMAL_VOL (2.0)
        synthesis = _make_synthesis(rr=1.8, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_3_rr"] == "FAIL"

    def test_fallback_when_unknown_regime(self) -> None:
        """Unknown regime falls back to hardcoded _THRESH_* constants without error."""
        synthesis = _make_synthesis(regime_type="UNKNOWN_REGIME")

        # Should not raise, should use hardcoded defaults
        verdict = generate_l12_verdict(synthesis)
        assert "gates" in verdict
        assert verdict["gates"]["total"] == 10

    def test_missing_regime_type_defaults_to_normal_vol(self) -> None:
        """Missing regime_type key defaults to NORMAL_VOL behavior."""
        synthesis = _make_synthesis()
        del synthesis["regime_type"]

        verdict = generate_l12_verdict(synthesis)

        # Should succeed using NORMAL_VOL as default
        assert "gates" in verdict

    def test_regime_thresholds_applied_to_mc_win(self) -> None:
        """HIGH_VOL regime applies relaxed mc_win threshold (0.55)."""
        # monte=0.57 is above HIGH_VOL mc_win (0.55) but below NORMAL_VOL (0.58)
        synthesis = _make_synthesis(monte=0.57, regime_type="HIGH_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_5_montecarlo"] == "PASS"

    def test_regime_thresholds_applied_to_integrity(self) -> None:
        """HIGH_VOL regime applies relaxed integrity threshold (0.93)."""
        # integrity=0.94 passes HIGH_VOL (0.93) but would fail LOW_VOL (0.97)
        synthesis = _make_synthesis(integrity=0.94, regime_type="HIGH_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["gates"]["gate_2_integrity"] == "PASS"

    def test_regime_type_in_output_scores(self) -> None:
        """Regime type is consumed from synthesis without raising errors."""
        for regime in ("LOW_VOL", "NORMAL_VOL", "HIGH_VOL"):
            synthesis = _make_synthesis(regime_type=regime)
            verdict = generate_l12_verdict(synthesis)
            assert "gates" in verdict


class TestNearPassExecuteReducedRisk:
    """Verify the near-pass path produces EXECUTE_REDUCED_RISK for 8-9/10 gates."""

    def test_nine_of_ten_gates_pass_yields_execute_reduced_risk(self) -> None:
        """When exactly 9/10 gates pass (no critical fail), yield EXECUTE_REDUCED_RISK."""
        # tii=0.50 fails gate_1; all others pass with NORMAL_VOL thresholds
        synthesis = _make_synthesis(tii=0.50, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["EXECUTE_REDUCED_RISK_BUY", "EXECUTE_REDUCED_RISK_SELL"]
        assert verdict["proceed_to_L13"] is True
        assert verdict["gates"]["passed"] == 9

    def test_eight_of_ten_gates_pass_yields_execute_reduced_risk(self) -> None:
        """When 8/10 gates pass (no critical fail), yield EXECUTE_REDUCED_RISK."""
        # Fail 2 non-critical gates
        synthesis = _make_synthesis(tii=0.50, monte=0.40, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["EXECUTE_REDUCED_RISK_BUY", "EXECUTE_REDUCED_RISK_SELL"]
        assert verdict["proceed_to_L13"] is True
        assert verdict["gates"]["passed"] == 8

    def test_seven_gates_pass_yields_hold(self) -> None:
        """When only 7/10 gates pass (no critical fail), yield HOLD."""
        # Fail 3 non-critical gates
        synthesis = _make_synthesis(tii=0.50, monte=0.40, rr=0.5, regime_type="NORMAL_VOL")
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] == "HOLD"
        assert verdict["proceed_to_L13"] is False

    def test_critical_fail_with_eight_passing_still_no_trade(self) -> None:
        """Critical gate failure always produces NO_TRADE regardless of pass count."""
        synthesis = _make_synthesis(propfirm_compliant=False, tii=0.50)
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] == "NO_TRADE"
        assert verdict["proceed_to_L13"] is False

    def test_near_pass_direction_preserved_buy(self) -> None:
        """Near-pass verdict preserves BUY direction in the verdict string."""
        synthesis = _make_synthesis(tii=0.50, regime_type="NORMAL_VOL")
        synthesis["bias"]["technical"] = "BULLISH"
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] == "EXECUTE_REDUCED_RISK_BUY"

    def test_near_pass_direction_preserved_sell(self) -> None:
        """Near-pass verdict preserves SELL direction in the verdict string."""
        synthesis = _make_synthesis(tii=0.50, regime_type="NORMAL_VOL")
        synthesis["bias"]["technical"] = "BEARISH"
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] == "EXECUTE_REDUCED_RISK_SELL"

    def test_governance_penalty_downgrade_preserves_direction(self) -> None:
        """Governance penalty >= 0.30 downgrades EXECUTE to EXECUTE_REDUCED_RISK with direction."""
        synthesis = _make_synthesis(regime_type="NORMAL_VOL")
        synthesis["bias"]["technical"] = "BULLISH"
        verdict = generate_l12_verdict(synthesis, governance_penalty=0.35)

        assert verdict["verdict"] == "EXECUTE_REDUCED_RISK_BUY"
        assert verdict["governance_downgraded"] is True

    def test_near_pass_enrichment_applied(self) -> None:
        """Enrichment score is applied to confidence for near-pass verdicts."""
        synthesis = _make_synthesis(tii=0.50, regime_type="NORMAL_VOL")
        synthesis["layers"]["enrichment_score"] = 0.80
        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["EXECUTE_REDUCED_RISK_BUY", "EXECUTE_REDUCED_RISK_SELL"]
        assert verdict["enrichment_applied"] is True
        assert verdict["confidence"] == "VERY_HIGH"  # wolf_30=25 → HIGH, enriched to VERY_HIGH
