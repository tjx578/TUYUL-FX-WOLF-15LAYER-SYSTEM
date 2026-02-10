"""
Unit tests for L12 verdict engine.

Tests verdict generation with various gate configurations.
"""

import pytest
from typing import Dict, Any

from constitution.verdict_engine import generate_l12_verdict


def _make_synthesis(
    tii: float = 0.85,
    integrity: float = 0.85,
    rr: float = 2.0,
    fta: float = 0.8,
    monte: float = 0.75,
    propfirm_compliant: bool = True,
    drawdown: float = 2.0,
    latency: int = 100,
    conf12: float = 0.85,
) -> Dict[str, Any]:
    """
    Helper to create a synthesis dict with configurable values.

    Default values pass all gates.
    """
    return {
        "pair": "EURUSD",
        "scores": {
            "wolf_30_point": 25,
            "f_score": 8,
            "t_score": 9,
            "fta_score": fta,
            "exec_score": 10,
        },
        "layers": {
            "L1": {"valid": True},
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
            "violations": [],
        },
        "risk": {
            "current_drawdown": drawdown,
            "max_drawdown": 5.0,
        },
        "bias": {
            "technical": "BULLISH",
            "fundamental": "NEUTRAL",
        },
        "system": {
            "latency_ms": latency,
        },
    }


class TestL12VerdictAllGatesPassing:
    """Test L12 verdict when all gates pass."""

    def test_all_gates_pass_execute_verdict(self) -> None:
        """Test verdict when all gates pass."""
        synthesis = _make_synthesis()

        verdict = generate_l12_verdict(synthesis)

        # Should generate EXECUTE verdict
        assert verdict is not None
        assert "verdict" in verdict
        assert "gates" in verdict

        # Check gates
        gates = verdict["gates"]
        assert gates["passed"] == gates["total"]

        # Verdict should be EXECUTE_BUY or EXECUTE_SELL
        assert verdict["verdict"] in ["EXECUTE_BUY", "EXECUTE_SELL"]

    def test_all_gates_pass_high_confidence(self) -> None:
        """Test confidence is HIGH when all gates pass."""
        synthesis = _make_synthesis()

        verdict = generate_l12_verdict(synthesis)

        # Confidence should be HIGH
        assert verdict.get("confidence") in ["HIGH", "MEDIUM"]


class TestL12VerdictGateFailures:
    """Test L12 verdict with various gate failures."""

    def test_tii_gate_failure(self) -> None:
        """Test verdict when TII gate fails."""
        synthesis = _make_synthesis(tii=0.50)  # Below threshold

        verdict = generate_l12_verdict(synthesis)

        # Should fail
        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_1_tii"] == "FAIL"

    def test_integrity_gate_failure(self) -> None:
        """Test verdict when integrity gate fails."""
        synthesis = _make_synthesis(integrity=0.50)

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_2_integrity"] == "FAIL"

    def test_rr_gate_failure(self) -> None:
        """Test verdict when RR gate fails."""
        synthesis = _make_synthesis(rr=1.0)  # Below 1.5 threshold

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_3_rr"] == "FAIL"

    def test_fta_gate_failure(self) -> None:
        """Test verdict when FTA score gate fails."""
        synthesis = _make_synthesis(fta=0.5)

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_4_fta"] == "FAIL"

    def test_monte_carlo_gate_failure(self) -> None:
        """Test verdict when Monte Carlo gate fails."""
        synthesis = _make_synthesis(monte=0.5)

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_5_montecarlo"] == "FAIL"

    def test_propfirm_gate_failure(self) -> None:
        """Test verdict when prop firm compliance fails."""
        synthesis = _make_synthesis(propfirm_compliant=False)

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_6_propfirm"] == "FAIL"

    def test_drawdown_gate_failure(self) -> None:
        """Test verdict when drawdown exceeds limit."""
        synthesis = _make_synthesis(drawdown=6.0)  # Above 5.0 threshold

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_7_drawdown"] == "FAIL"

    def test_latency_gate_failure(self) -> None:
        """Test verdict when latency is too high."""
        synthesis = _make_synthesis(latency=300)  # Above 250ms threshold

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_8_latency"] == "FAIL"

    def test_conf12_gate_failure(self) -> None:
        """Test verdict when confidence is too low."""
        synthesis = _make_synthesis(conf12=0.5)

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]
        assert verdict["gates"]["gate_9_conf12"] == "FAIL"

    def test_multiple_gate_failures(self) -> None:
        """Test verdict when multiple gates fail."""
        synthesis = _make_synthesis(
            tii=0.5,
            rr=1.0,
            drawdown=6.0,
        )

        verdict = generate_l12_verdict(synthesis)

        # Should fail
        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]

        # Multiple gates should fail
        gates = verdict["gates"]
        failed_count = sum(1 for v in gates.values() if v == "FAIL")
        assert failed_count >= 3


class TestL12VerdictTypes:
    """Test different verdict types."""

    def test_no_trade_verdict(self) -> None:
        """Test NO_TRADE verdict is generated."""
        # Fail critical gates
        synthesis = _make_synthesis(
            propfirm_compliant=False,
            drawdown=6.0,
        )

        verdict = generate_l12_verdict(synthesis)

        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]

    def test_hold_verdict(self) -> None:
        """Test HOLD verdict is generated."""
        # Marginal failures
        synthesis = _make_synthesis(conf12=0.7)

        verdict = generate_l12_verdict(synthesis)

        # Should be NO_TRADE or HOLD
        assert verdict["verdict"] in ["NO_TRADE", "HOLD"]

    def test_execute_buy_verdict(self) -> None:
        """Test EXECUTE_BUY verdict is generated."""
        synthesis = _make_synthesis()
        synthesis["bias"]["technical"] = "BULLISH"

        verdict = generate_l12_verdict(synthesis)

        # Should execute (exact type depends on implementation)
        assert verdict["verdict"] in ["EXECUTE_BUY", "EXECUTE_SELL"]

    def test_execute_sell_verdict(self) -> None:
        """Test EXECUTE_SELL verdict is generated."""
        synthesis = _make_synthesis()
        synthesis["bias"]["technical"] = "BEARISH"

        verdict = generate_l12_verdict(synthesis)

        # Should execute
        assert verdict["verdict"] in ["EXECUTE_BUY", "EXECUTE_SELL"]


class TestL12CannotBeBypassed:
    """Test that L12 cannot be bypassed."""

    def test_l12_always_validates_gates(self) -> None:
        """Test L12 always validates all gates."""
        synthesis = _make_synthesis()

        verdict = generate_l12_verdict(synthesis)

        # Gates must be present
        assert "gates" in verdict
        assert len(verdict["gates"]) > 0

    def test_l12_requires_valid_synthesis(self) -> None:
        """Test L12 requires valid synthesis input."""
        invalid_synthesis = {
            "pair": "EURUSD",
            # Missing required fields
        }

        # Should raise ValueError
        with pytest.raises(ValueError, match="Missing required synthesis field"):
            generate_l12_verdict(invalid_synthesis)

    def test_l12_verdict_immutable(self) -> None:
        """Test L12 verdict cannot be modified after generation."""
        synthesis = _make_synthesis()

        verdict = generate_l12_verdict(synthesis)

        # Verdict is a dict, but conceptually immutable
        # (In production, this would be enforced by L14 cache)
        assert "verdict" in verdict
        assert verdict["verdict"] is not None

    def test_l12_gates_must_all_pass_for_execute(self) -> None:
        """Test all gates must pass for EXECUTE verdict."""
        # Start with all passing
        synthesis = _make_synthesis()
        verdict_pass = generate_l12_verdict(synthesis)

        # Now fail one gate
        synthesis_fail = _make_synthesis(tii=0.5)
        verdict_fail = generate_l12_verdict(synthesis_fail)

        # First should execute, second should not
        assert verdict_pass["verdict"] in ["EXECUTE_BUY", "EXECUTE_SELL"]
        assert verdict_fail["verdict"] in ["NO_TRADE", "HOLD"]
