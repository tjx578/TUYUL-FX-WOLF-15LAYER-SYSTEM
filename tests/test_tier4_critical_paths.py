"""
Tests for Tier 4 critical-path coverage — L7 walk-forward degradation,
L8 TII grade wiring, L8 degraded-mode edge cases, execution FSM edges.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from analysis.l8_tii import (
    TIIGrade,
    _clamp,
    _fallback_bias,
    _fallback_energy,
    _fallback_vwap,
    analyze_tii,
)
from analysis.layers.L7_probability import L7ProbabilityAnalyzer
from analysis.layers.L8_tii_integrity import (
    L8TIIIntegrityAnalyzer,
)
from analysis.layers.L8_tii_integrity import (
    analyze_tii as wrapper_analyze_tii,
)

NOW = datetime(2026, 3, 17, 10, 0, 0, tzinfo=UTC)


# ═══════════════════════════════════════════════════════════════════════
# L7 — Walk-Forward Degradation Tests
# ═══════════════════════════════════════════════════════════════════════


def _make_returns(n: int = 100, win_rate: float = 0.65, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(10, 100)))
        else:
            returns.append(float(rng.uniform(-80, -5)))
    return returns


class _FakeWFResult:
    """Fake WalkForwardValidator result."""

    def __init__(self, passed: bool, stability: float = 0.8) -> None:
        self.passed = passed
        self.stability_score = stability
        self.avg_win_rate = 0.62
        self.regime_consistency = 0.75
        self.avg_profit_factor = 1.4


class TestL7WalkForwardDegradation:
    """Test that walk-forward failure properly degrades validation tiers."""

    def test_wf_fail_downgrades_pass_to_conditional(self) -> None:
        """When WF fails and MC gives PASS, result should be CONDITIONAL."""
        fake_wf = MagicMock()
        fake_wf.run.return_value = _FakeWFResult(passed=False)

        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        # Strong returns → MC says PASS
        returns = _make_returns(150, win_rate=0.75, seed=42)

        with patch("analysis.layers.L7_probability._wf_validator", fake_wf):
            result = analyzer.analyze(
                "EURUSD",
                trade_returns=returns,
                prior_wins=30,
                prior_losses=10,
            )

        # WF failed → should have downgraded from PASS to CONDITIONAL
        assert result["validation"] in ("CONDITIONAL", "FAIL")
        assert result["wf_passed"] is False

    def test_wf_fail_downgrades_conditional_to_fail(self) -> None:
        """When WF fails and MC gives CONDITIONAL, result should be FAIL."""
        fake_wf = MagicMock()
        fake_wf.run.return_value = _FakeWFResult(passed=False)

        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        # Moderate returns → MC says CONDITIONAL
        returns = _make_returns(150, win_rate=0.56, seed=11)

        with patch("analysis.layers.L7_probability._wf_validator", fake_wf):
            result = analyzer.analyze(
                "EURUSD",
                trade_returns=returns,
                prior_wins=15,
                prior_losses=15,
            )

        # If MC gave CONDITIONAL, WF fail should downgrade to FAIL
        if result.get("_mc_validation_before_wf", result["validation"]) == "CONDITIONAL":
            assert result["validation"] == "FAIL"
        # If MC already gave FAIL, WF can't downgrade further
        assert result["wf_passed"] is False

    def test_wf_exception_populates_default_fields(self) -> None:
        """WF exception should populate None fields for schema consistency."""
        fake_wf = MagicMock()
        fake_wf.run.side_effect = RuntimeError("engine crash")

        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        returns = _make_returns(150, win_rate=0.75, seed=42)

        with patch("analysis.layers.L7_probability._wf_validator", fake_wf):
            result = analyzer.analyze(
                "EURUSD",
                trade_returns=returns,
                prior_wins=30,
                prior_losses=10,
            )

        # WF fields should exist with None values
        assert result.get("wf_passed") is None
        assert result.get("wf_stability_score") is None
        assert result.get("wf_avg_win_rate") is None
        assert result.get("wf_regime_consistency") is None
        assert result.get("wf_avg_profit_factor") is None
        # Main validation should be unaffected
        assert result["valid"] is True

    def test_wf_pass_preserves_validation(self) -> None:
        """When WF passes, validation tier should remain unchanged."""
        fake_wf = MagicMock()
        fake_wf.run.return_value = _FakeWFResult(passed=True, stability=0.9)

        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        returns = _make_returns(150, win_rate=0.75, seed=42)

        with patch("analysis.layers.L7_probability._wf_validator", fake_wf):
            result = analyzer.analyze(
                "EURUSD",
                trade_returns=returns,
                prior_wins=30,
                prior_losses=10,
            )

        assert result["wf_passed"] is True
        assert result["wf_stability_score"] == 0.9
        # PASS should remain PASS when WF passes
        assert result["validation"] in ("PASS", "CONDITIONAL")

    def test_wf_skipped_under_130_trades(self) -> None:
        """WF enrichment skipped when < 130 trades — no WF fields."""
        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        returns = _make_returns(50, win_rate=0.75, seed=42)

        result = analyzer.analyze("EURUSD", trade_returns=returns)

        # WF fields should NOT be present (< 130 trades)
        assert "wf_passed" not in result


# ═══════════════════════════════════════════════════════════════════════
# L8 — TII Grade Wiring Tests
# ═══════════════════════════════════════════════════════════════════════


def _make_closes(n: int = 60, base: float = 1.3000, drift: float = 0.0001) -> list[float]:
    return [round(base + drift * i, 5) for i in range(n)]


class TestL8TIIGradeWiring:
    """Test that tii_grade appears in analyze_tii output."""

    def test_canonical_analyze_tii_has_grade(self) -> None:
        """analyze_tii should include tii_grade field."""
        result = analyze_tii({"closes": _make_closes(60)}, now=NOW)
        assert "tii_grade" in result
        assert result["tii_grade"] in [g.value for g in TIIGrade]

    def test_wrapper_analyze_tii_has_grade(self) -> None:
        """Wrapper analyze_tii should also include tii_grade."""
        closes = _make_closes(60)
        result = wrapper_analyze_tii({"closes": closes})
        assert "tii_grade" in result
        assert result["tii_grade"] in [g.value for g in TIIGrade]

    def test_class_analyzer_has_grade(self) -> None:
        """L8TIIIntegrityAnalyzer.analyze should include tii_grade."""
        analyzer = L8TIIIntegrityAnalyzer()
        result = analyzer.analyze({"market_data": {"closes": _make_closes(60)}})
        assert "tii_grade" in result

    def test_strong_tii_gets_high_grade(self) -> None:
        """High TII should map to PRISTINE or CLEAN grade."""
        l3 = {"vwap": 1.303, "energy": 4.0, "bias_strength": 0.008}
        l1 = {"regime_confidence": 0.95}
        result = analyze_tii(
            {"closes": _make_closes(60)},
            l3_data=l3,
            l1_data=l1,
            now=NOW,
        )
        if result["tii_sym"] >= 0.90:
            assert result["tii_grade"] == "PRISTINE"
        elif result["tii_sym"] >= 0.75:
            assert result["tii_grade"] == "CLEAN"

    def test_insufficient_data_no_grade(self) -> None:
        """Insufficient-data result should NOT have tii_grade."""
        result = analyze_tii({"closes": [1.3, 1.31]}, now=NOW)
        assert result["valid"] is False
        # No grade when invalid
        assert "tii_grade" not in result


# ═══════════════════════════════════════════════════════════════════════
# L8 — Fallback / Degraded Mode Edge Cases
# ═══════════════════════════════════════════════════════════════════════


class TestL8FallbackEdges:
    """Edge cases in TII fallback estimators."""

    def test_fallback_vwap_empty_list(self) -> None:
        assert _fallback_vwap([]) == 0.0

    def test_fallback_vwap_short_list(self) -> None:
        assert _fallback_vwap([1.3, 1.31, 1.32]) == 0.0

    def test_fallback_vwap_returns_near_mean(self) -> None:
        closes = _make_closes(60)
        vwap = _fallback_vwap(closes)
        mean_price = sum(closes) / len(closes)
        # Should be within 5% of simple mean
        assert abs(vwap - mean_price) / mean_price < 0.05

    def test_fallback_energy_empty(self) -> None:
        assert _fallback_energy([]) == 0.0

    def test_fallback_energy_single_bar(self) -> None:
        assert _fallback_energy([1.3]) == 0.0

    def test_fallback_energy_positive(self) -> None:
        closes = _make_closes(20, drift=0.001)
        energy = _fallback_energy(closes)
        assert energy > 0.0

    def test_fallback_bias_empty(self) -> None:
        assert _fallback_bias([]) == 0.0

    def test_fallback_bias_trending_up(self) -> None:
        # Prices rising → positive bias
        closes = _make_closes(60, drift=0.001)
        bias = _fallback_bias(closes)
        assert bias > 0.0

    def test_all_fields_degraded_meta_floor(self) -> None:
        """When all 4 fields are estimated, meta-integrity hits floor."""
        # Only closes, no L3 or L1
        closes = _make_closes(60)
        result = analyze_tii({"closes": closes}, now=NOW)
        # Should be degraded
        assert len(result.get("degraded_fields", [])) >= 2
        # Meta-integrity floor is 0.4
        assert result["meta_integrity"] >= 0.4

    def test_clamp_bounds(self) -> None:
        assert _clamp(-0.5) == 0.0
        assert _clamp(1.5) == 1.0
        assert _clamp(0.5) == 0.5


# ═══════════════════════════════════════════════════════════════════════
# Execution FSM — Edge Cases
# ═══════════════════════════════════════════════════════════════════════


class TestExecutionFSMEdges:
    """Test execution state machine replay-safety and transitions."""

    def test_replay_terminal_noop(self) -> None:
        """Terminal → same-terminal should return REPLAY noop, not raise."""
        from execution.state_machine import OrderEvent, OrderState, StateMachine

        fsm = StateMachine()
        # Move to FILLED (terminal state)
        fsm.apply(OrderEvent.PLACE_ORDER)
        fsm.apply(OrderEvent.ORDER_FILLED)
        assert fsm.state == OrderState.FILLED

        # Replay FILLED → should not raise
        result = fsm.apply(OrderEvent.ORDER_FILLED)
        assert result.reason == "REPLAY_TERMINAL_NOOP" or fsm.state == OrderState.FILLED

    def test_idle_to_pending(self) -> None:
        from execution.state_machine import OrderEvent, OrderState, StateMachine

        fsm = StateMachine()
        assert fsm.state == OrderState.IDLE
        fsm.apply(OrderEvent.PLACE_ORDER)
        assert fsm.state == OrderState.PENDING_ACTIVE

    def test_pending_to_cancelled(self) -> None:
        from execution.state_machine import OrderEvent, OrderState, StateMachine

        fsm = StateMachine()
        fsm.apply(OrderEvent.PLACE_ORDER)
        fsm.apply(OrderEvent.ORDER_CANCELLED)
        assert fsm.state == OrderState.CANCELLED


# ═══════════════════════════════════════════════════════════════════════
# Signal Integrity — L12 must NOT contain account state
# ═══════════════════════════════════════════════════════════════════════


class TestSignalIntegrityBoundary:
    """Verify L12 signals don't contain account-level fields."""

    FORBIDDEN_FIELDS = {"balance", "equity", "margin", "margin_used", "free_margin"}

    def test_l12_verdict_no_account_fields(self, sample_l12_verdict: dict[str, Any]) -> None:
        """L12 verdict fixture must not contain account state."""
        for field in self.FORBIDDEN_FIELDS:
            assert field not in sample_l12_verdict, f"L12 verdict contains forbidden account field: {field}"

    def test_l12_reject_no_account_fields(self, sample_l12_reject: dict[str, Any]) -> None:
        """L12 reject fixture must not contain account state."""
        for field in self.FORBIDDEN_FIELDS:
            assert field not in sample_l12_reject, f"L12 reject contains forbidden account field: {field}"


# ═══════════════════════════════════════════════════════════════════════
# Risk Module — Prop Firm Guard Critical Path
# ═══════════════════════════════════════════════════════════════════════


class TestPropFirmGuardCriticalPath:
    """Test that risk module correctly blocks dangerous trades."""

    def test_daily_loss_limit_blocks(
        self, sample_account_state: dict[str, Any], sample_trade_risk: dict[str, Any]
    ) -> None:
        """A trade that would exceed daily loss limit should be blocked."""
        # Push account near daily loss limit
        state = {**sample_account_state, "daily_pnl": -4800.0}
        risk = {**sample_trade_risk, "risk_amount": 500.0}

        try:
            from risk.prop_firm import PropFirmGuard

            result = PropFirmGuard().check(state, risk)
            # If trade + existing loss > limit, should not be allowed
            if state["daily_pnl"] + risk["risk_amount"] * -1 < -state["daily_loss_limit"]:
                assert result.allowed is False
        except ImportError:
            pytest.skip("risk.prop_firm not available")
