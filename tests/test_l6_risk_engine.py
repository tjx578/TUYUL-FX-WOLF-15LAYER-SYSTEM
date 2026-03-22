"""Tests: L6 Capital Firewall Risk Engine (v4 PRODUCTION).

Covers:
  1. Drawdown tier classification + hard block
  2. Volatility cluster adjustments
  3. Correlation exposure dampening
  4. LRCE field instability (Lorentzian Risk Compression Estimator)
  5. Rolling Sharpe degradation
  6. Kelly fraction dampener
  7. Prop-firm hard-block rules
  8. Backward compatibility (analyze(rr=...) still works)
  9. Correlation Risk Engine integration (when available)
"""

from __future__ import annotations

import pytest

from analysis.layers.L6_risk import L6RiskAnalyzer

# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> L6RiskAnalyzer:
    return L6RiskAnalyzer()


# ─────────────────────────────────────────────────────────────────────
# 1. Backward Compatibility
# ─────────────────────────────────────────────────────────────────────


class TestBackwardCompat:
    """Old-style analyze(rr=...) still works with sensible defaults."""

    def test_minimal_call(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.0)
        assert result["valid"] is True
        assert result["risk_ok"] is True
        assert result["risk_status"] == "OPTIMAL"
        assert result["drawdown_level"] == "LEVEL_0"
        assert result["risk_multiplier"] == 1.0
        assert "lrce" in result
        assert "rolling_sharpe" in result
        assert "kelly_adjusted" in result

    def test_default_rr(self, engine: L6RiskAnalyzer) -> None:
        """No arguments at all → uses defaults."""
        result = engine.analyze()
        assert result["valid"] is True
        assert result["risk_ok"] is True

    def test_result_keys_complete(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.5)
        required_keys = {
            "risk_status",
            "propfirm_compliant",
            "drawdown_level",
            "risk_multiplier",
            "lrce",
            "rolling_sharpe",
            "kelly_adjusted",
            "max_risk_pct",
            "risk_ok",
            "valid",
            "warnings",
            "rr_ratio",
            "current_drawdown",
        }
        assert required_keys.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────────
# 2. Drawdown Tiers
# ─────────────────────────────────────────────────────────────────────


class TestDrawdownTiers:
    """Drawdown classification and risk multiplier scaling."""

    def test_level_0_no_drawdown(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"drawdown_pct": 0.0})
        assert result["drawdown_level"] == "LEVEL_0"
        assert result["risk_multiplier"] == 1.0
        assert result["risk_ok"] is True

    def test_level_1_mild_drawdown(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"drawdown_pct": 0.03})
        assert result["drawdown_level"] == "LEVEL_1"
        assert result["risk_multiplier"] == 0.8
        assert result["risk_ok"] is True

    def test_level_2_moderate_drawdown(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"drawdown_pct": 0.05})
        assert result["drawdown_level"] == "LEVEL_2"
        assert result["risk_multiplier"] == 0.5
        assert result["risk_ok"] is True

    def test_level_3_defensive(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"drawdown_pct": 0.07})
        assert result["drawdown_level"] == "LEVEL_3"
        assert result["risk_multiplier"] == 0.3
        assert result["risk_status"] == "DEFENSIVE"
        assert result["risk_ok"] is True

    def test_level_4_hard_block(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"drawdown_pct": 0.09})
        assert result["drawdown_level"] == "LEVEL_4"
        assert result["risk_status"] == "CRITICAL"
        assert result["risk_ok"] is False
        assert result["propfirm_compliant"] is False
        assert result["max_risk_pct"] == 0.0

    def test_equity_based_drawdown(self, engine: L6RiskAnalyzer) -> None:
        """When equity + peak provided, drawdown is computed not read."""
        result = engine.analyze(
            account_state={"equity": 95000, "peak_equity": 100000},
        )
        assert result["drawdown_level"] == "LEVEL_2"  # 5% DD
        assert result["current_drawdown"] == pytest.approx(0.05, abs=0.001)

    def test_consecutive_losses_scaling(self, engine: L6RiskAnalyzer) -> None:
        result_2 = engine.analyze(account_state={"consecutive_losses": 2})
        result_3 = engine.analyze(account_state={"consecutive_losses": 3})
        assert result_2["risk_multiplier"] == 0.75
        assert result_3["risk_multiplier"] == 0.5
        assert "CONSECUTIVE_LOSSES_3" in result_3["warnings"]


# ─────────────────────────────────────────────────────────────────────
# 3. Volatility Cluster Adjustment
# ─────────────────────────────────────────────────────────────────────


class TestVolatilityCluster:
    def test_extreme_vol(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"vol_cluster": "EXTREME"})
        assert result["risk_multiplier"] == 0.5

    def test_high_vol(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"vol_cluster": "HIGH"})
        assert result["risk_multiplier"] == 0.7

    def test_normal_vol(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"vol_cluster": "NORMAL"})
        assert result["risk_multiplier"] == 1.0


# ─────────────────────────────────────────────────────────────────────
# 4. Correlation Exposure Dampener
# ─────────────────────────────────────────────────────────────────────


class TestCorrelationExposure:
    def test_high_correlation_dampens(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"corr_exposure": 0.8})
        assert result["risk_multiplier"] == 0.6
        assert result["risk_status"] == "CORRELATION_STRESS"

    def test_low_correlation_no_change(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(account_state={"corr_exposure": 0.5})
        assert result["risk_multiplier"] == 1.0
        assert result["risk_status"] == "OPTIMAL"


# ─────────────────────────────────────────────────────────────────────
# 5. LRCE — Lorentzian Risk Compression Estimator
# ─────────────────────────────────────────────────────────────────────


class TestLRCE:
    def test_stable_field(self, engine: L6RiskAnalyzer) -> None:
        """Coherent enrichment → low lrce → no block."""
        enrichment = {
            "fusion_momentum": 0.5,
            "quantum_probability": 0.5,
            "bias_strength": 0.6,
            "posterior": 0.6,
        }
        result = engine.analyze(enrichment=enrichment)
        assert result["lrce"] < 0.2
        assert result["risk_ok"] is True

    def test_mild_instability(self, engine: L6RiskAnalyzer) -> None:
        enrichment = {
            "fusion_momentum": 0.7,
            "quantum_probability": 0.4,
            "bias_strength": 0.8,
            "posterior": 0.6,
        }
        result = engine.analyze(enrichment=enrichment)
        assert 0.2 <= result["lrce"] <= 0.6
        assert result["risk_ok"] is True  # below block threshold

    def test_field_fracture_blocks(self, engine: L6RiskAnalyzer) -> None:
        """LRCE > 0.6 → hard block."""
        enrichment = {
            "fusion_momentum": 0.9,
            "quantum_probability": 0.1,
            "bias_strength": 0.9,
            "posterior": 0.2,
        }
        result = engine.analyze(enrichment=enrichment)
        assert result["lrce"] > 0.6
        assert result["risk_ok"] is False
        assert result["risk_status"] == "UNSTABLE_FIELD"
        assert result["max_risk_pct"] == 0.0

    def test_no_enrichment_lrce_zero(self, engine: L6RiskAnalyzer) -> None:
        """Without enrichment, LRCE defaults to 0.0 (no block)."""
        result = engine.analyze()
        assert result["lrce"] == 0.0
        assert result["risk_ok"] is True

    def test_lrce_clamped_at_1(self, engine: L6RiskAnalyzer) -> None:
        enrichment = {
            "fusion_momentum": 1.0,
            "quantum_probability": 0.0,
            "bias_strength": 1.0,
            "posterior": 0.0,
        }
        result = engine.analyze(enrichment=enrichment)
        assert result["lrce"] == 1.0


# ─────────────────────────────────────────────────────────────────────
# 6. Prop-Firm Hard Rules
# ─────────────────────────────────────────────────────────────────────


class TestPropFirmRules:
    def test_daily_dd_breach(self, engine: L6RiskAnalyzer) -> None:
        """Daily DD exceeding limit → hard block."""
        result = engine.analyze(
            account_state={"daily_loss_pct": 0.06},  # 6% > 5% default
        )
        assert result["risk_ok"] is False
        assert result["risk_status"] == "DAILY_LIMIT_BREACH"

    def test_total_dd_breach(self, engine: L6RiskAnalyzer) -> None:
        """Total DD exceeding limit → hard block."""
        result = engine.analyze(
            account_state={"drawdown_pct": 0.12},  # 12% > 10% default
        )
        assert result["risk_ok"] is False
        assert result["risk_status"] == "TOTAL_DD_BREACH"

    def test_within_limits_passes(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(
            account_state={"drawdown_pct": 0.01, "daily_loss_pct": 0.01},
        )
        assert result["risk_ok"] is True
        assert result["propfirm_compliant"] is True


# ─────────────────────────────────────────────────────────────────────
# 7. Kelly Dampener
# ─────────────────────────────────────────────────────────────────────


class TestKellyDampener:
    def test_no_drawdown_full_kelly(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(
            account_state={"base_kelly": 0.25, "drawdown_pct": 0.0},
        )
        assert result["kelly_adjusted"] == 0.25

    def test_mild_drawdown_reduces_kelly(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(
            account_state={"base_kelly": 0.25, "drawdown_pct": 0.03},
        )
        assert result["kelly_adjusted"] == pytest.approx(0.2, abs=0.01)

    def test_extreme_drawdown_freezes_kelly(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(
            account_state={"base_kelly": 0.25, "drawdown_pct": 0.09},
        )
        assert result["kelly_adjusted"] == 0.0

    def test_hard_block_zeroes_kelly(self, engine: L6RiskAnalyzer) -> None:
        """Even with base_kelly set, hard block zeroes it."""
        result = engine.analyze(
            account_state={"base_kelly": 0.25, "drawdown_pct": 0.09},
        )
        assert result["kelly_adjusted"] == 0.0


# ─────────────────────────────────────────────────────────────────────
# 8. Rolling Sharpe Degradation
# ─────────────────────────────────────────────────────────────────────


class TestRollingSharpe:
    def test_insufficient_data_returns_zero(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(trade_returns=[0.01] * 10)
        assert result["rolling_sharpe"] == 0.0

    def test_good_sharpe_no_degradation(self, engine: L6RiskAnalyzer) -> None:
        """Positive Sharpe above threshold → no degradation penalty."""
        import numpy as np  # noqa: PLC0415

        rng = np.random.default_rng(42)
        # Positive mean returns → good Sharpe
        returns = [float(x) for x in rng.normal(0.02, 0.01, 60)]
        result = engine.analyze(trade_returns=returns)
        assert result["rolling_sharpe"] > engine.sharpe_degradation_threshold
        assert "SHARPE_DEGRADATION" not in str(result["warnings"])


# ─────────────────────────────────────────────────────────────────────
# 9. Combined Scenarios
# ─────────────────────────────────────────────────────────────────────


class TestCombinedScenarios:
    def test_drawdown_plus_vol_compound(self, engine: L6RiskAnalyzer) -> None:
        """DD LEVEL_1 (0.8) × HIGH vol (0.7) = 0.56."""
        result = engine.analyze(
            account_state={"drawdown_pct": 0.03, "vol_cluster": "HIGH"},
        )
        assert result["risk_multiplier"] == pytest.approx(0.56, abs=0.01)

    def test_multiple_blocks_set_zero_risk(self, engine: L6RiskAnalyzer) -> None:
        """DD breach + LRCE fracture → still risk_ok=False, risk=0."""
        result = engine.analyze(
            account_state={"drawdown_pct": 0.09},
            enrichment={
                "fusion_momentum": 0.9,
                "quantum_probability": 0.1,
                "bias_strength": 0.9,
                "posterior": 0.2,
            },
        )
        assert result["risk_ok"] is False
        assert result["max_risk_pct"] == 0.0
        assert result["kelly_adjusted"] == 0.0

    def test_low_rr_advisory_warning(self, engine: L6RiskAnalyzer) -> None:
        """Low RR is advisory only — does not block."""
        result = engine.analyze(rr=1.0)
        assert result["risk_ok"] is True  # not blocked
        assert any("LOW_RR_RATIO" in w for w in result["warnings"])


# ─────────────────────────────────────────────────────────────────────
# 10. Correlation Engine Integration (when engine available)
# ─────────────────────────────────────────────────────────────────────


class TestCorrelationEngineIntegration:
    """Tests for CorrelationRiskEngine integration (optional enrichment)."""

    def test_no_pair_returns_no_corr_impact(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.0)
        assert result["risk_status"] == "OPTIMAL"
        assert result["risk_ok"] is True

    def test_single_pair_skipped(self, engine: L6RiskAnalyzer) -> None:
        """Only 1 pair → correlation analysis skipped (need >= 2)."""
        result = engine.analyze(
            pair_returns={"EURUSD": [float(x) for x in range(50)]},
        )
        assert result["risk_ok"] is True  # no corr impact

    def test_short_series_skipped(self, engine: L6RiskAnalyzer) -> None:
        """Series < 20 observations → correlation analysis skipped."""
        result = engine.analyze(
            pair_returns={
                "EURUSD": [1.0] * 10,
                "GBPUSD": [2.0] * 10,
            },
        )
        assert result["risk_ok"] is True
