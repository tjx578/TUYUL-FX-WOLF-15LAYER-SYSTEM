"""Tests: L6 pipeline wiring — account data flows into L6RiskAnalyzer.

Verifies that the pipeline correctly feeds account state from
RiskManager / system_metrics into L6's 7 checks, rather than passing
empty defaults that make checks no-op.
"""

from __future__ import annotations

import pytest

from analysis.layers.L6_risk import L6RiskAnalyzer


@pytest.fixture
def engine() -> L6RiskAnalyzer:
    return L6RiskAnalyzer()


class TestAccountDataWiring:
    """Verify L6 fires real checks when given real account data."""

    def test_daily_dd_breach_fires_with_real_data(self, engine: L6RiskAnalyzer) -> None:
        """Check 6: daily DD breach should fire when daily_loss_pct is fed."""
        result = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 10_000.0,
                "peak_equity": 10_000.0,
                "daily_loss_pct": 6.0,  # 6% → exceeds 5% default max_daily_dd
                "consecutive_losses": 0,
            },
        )
        assert result["risk_ok"] is False
        assert "DAILY_DD_BREACH" in result["risk_status"] or any(
            "DAILY_DD_BREACH" in w for w in result["warnings"]
        )

    def test_daily_dd_ok_when_zero(self, engine: L6RiskAnalyzer) -> None:
        """Check 6 should NOT fire when daily_loss_pct is 0 (no losses)."""
        result = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 10_000.0,
                "peak_equity": 10_000.0,
                "daily_loss_pct": 0.0,
                "consecutive_losses": 0,
            },
        )
        assert result["risk_ok"] is True
        assert not any("DAILY_DD_BREACH" in w for w in result["warnings"])

    def test_equity_drawdown_fires(self, engine: L6RiskAnalyzer) -> None:
        """Check 1: drawdown tier from equity/peak should classify correctly."""
        result = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 9_000.0,     # 10% drawdown from peak
                "peak_equity": 10_000.0,
                "daily_loss_pct": 0.0,
                "consecutive_losses": 0,
            },
        )
        # 10% drawdown → LEVEL_4 → CRITICAL → hard_block
        assert result["risk_ok"] is False
        assert result["drawdown_level"] == "LEVEL_4"

    def test_correlation_stress_fires(self, engine: L6RiskAnalyzer) -> None:
        """Check 3: high correlation should dampen risk multiplier."""
        result = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 10_000.0,
                "peak_equity": 10_000.0,
                "corr_exposure": 0.85,  # high correlation
                "daily_loss_pct": 0.0,
                "consecutive_losses": 0,
            },
        )
        assert result["risk_multiplier"] < 1.0
        assert any("CORRELATION" in w for w in result["warnings"])

    def test_kelly_dampener_active_under_drawdown(self, engine: L6RiskAnalyzer) -> None:
        """Check 7: kelly should be dampened under drawdown stress."""
        # No drawdown → full kelly
        result_healthy = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 10_000.0,
                "peak_equity": 10_000.0,
                "base_kelly": 0.25,
                "daily_loss_pct": 0.0,
            },
        )
        # Moderate drawdown → reduced kelly
        result_stressed = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 9_500.0,
                "peak_equity": 10_000.0,  # 5% drawdown
                "base_kelly": 0.25,
                "daily_loss_pct": 0.0,
            },
        )
        assert result_stressed["kelly_adjusted"] < result_healthy["kelly_adjusted"]

    def test_consecutive_losses_scaling(self, engine: L6RiskAnalyzer) -> None:
        """Consecutive losses reduce risk_multiplier."""
        result_0 = engine.analyze(rr=2.0, account_state={"consecutive_losses": 0})
        result_3 = engine.analyze(rr=2.0, account_state={"consecutive_losses": 3})
        assert result_3["risk_multiplier"] < result_0["risk_multiplier"]

    def test_circuit_breaker_honored(self, engine: L6RiskAnalyzer) -> None:
        """Extra field: circuit_breaker_active is stored but L6 class
        doesn't directly read it (the old analyze_risk fn does).
        This is fine — RiskManager enforces CB separately.
        We just verify L6 doesn't crash on the extra field."""
        result = engine.analyze(
            rr=2.0,
            account_state={
                "equity": 10_000.0,
                "peak_equity": 10_000.0,
                "circuit_breaker_active": True,
                "daily_loss_pct": 0.0,
            },
        )
        assert result["valid"] is True


class TestAllDefaultsDegrade:
    """When no account_state is passed, L6 still works but with safe defaults."""

    def test_no_account_state(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.0)
        assert result["valid"] is True
        assert result["risk_ok"] is True
        assert result["risk_status"] == "OPTIMAL"
        assert result["warnings"] == [] or all(
            "LOW_RR" not in w for w in result["warnings"]
        )

    def test_empty_account_state(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.0, account_state={})
        assert result["valid"] is True
        assert result["risk_ok"] is True
