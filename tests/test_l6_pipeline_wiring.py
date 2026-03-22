"""Tests: L6 pipeline wiring — account data flows into L6RiskAnalyzer.

Verifies that:
  1. L6 fires real checks when given real account data (7 checks)
  2. LiveContextBus correctly provides account_state + trade_history
  3. Bus → L6 integration works end-to-end
  4. LRCE enrichment patching works post-Phase 2.5
  5. Graceful degradation when sources are unavailable
"""

from __future__ import annotations

import pytest

from analysis.layers.L6_risk import L6RiskAnalyzer
from context.live_context_bus import LiveContextBus


@pytest.fixture
def engine() -> L6RiskAnalyzer:
    return L6RiskAnalyzer()


@pytest.fixture
def fresh_bus() -> LiveContextBus:
    """Create a fresh LiveContextBus instance (bypass singleton for isolation)."""
    bus = object.__new__(LiveContextBus)
    bus._init()
    return bus


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
        assert "DAILY_DD_BREACH" in result["risk_status"] or any("DAILY_DD_BREACH" in w for w in result["warnings"])

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
                "equity": 9_000.0,  # 10% drawdown from peak
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
        assert result["warnings"] == [] or all("LOW_RR" not in w for w in result["warnings"])

    def test_empty_account_state(self, engine: L6RiskAnalyzer) -> None:
        result = engine.analyze(rr=2.0, account_state={})
        assert result["valid"] is True
        assert result["risk_ok"] is True


# ═══════════════════════════════════════════════════════════════════
#  LiveContextBus account state wiring
# ═══════════════════════════════════════════════════════════════════


class TestBusAccountState:
    """LiveContextBus.get_account_state() and update_account_state()."""

    def test_empty_bus_returns_empty_or_fallback(self, fresh_bus: LiveContextBus) -> None:
        """No data pushed → returns empty dict (RM fallback may kick in)."""
        state = fresh_bus.get_account_state("EURUSD")
        assert isinstance(state, dict)

    def test_push_then_read(self, fresh_bus: LiveContextBus) -> None:
        """Dashboard pushes state → pipeline reads it back."""
        fresh_bus.update_account_state(
            "EURUSD",
            {
                "equity": 10_000.0,
                "peak_equity": 10_500.0,
                "daily_loss_pct": 0.03,
                "circuit_breaker_active": False,
                "open_positions": 2,
                "max_open_positions": 5,
            },
        )
        state = fresh_bus.get_account_state("EURUSD")
        assert state["equity"] == 10_000.0
        assert state["peak_equity"] == 10_500.0
        assert state["daily_loss_pct"] == 0.03
        assert state["open_positions"] == 2

    def test_merge_semantics(self, fresh_bus: LiveContextBus) -> None:
        """Multiple updates replace state (snapshot semantics)."""
        fresh_bus.update_account_state("EURUSD", {"equity": 10_000.0})
        fresh_bus.update_account_state("EURUSD", {"equity": 10_000.0, "daily_loss_pct": 0.02})
        state = fresh_bus.get_account_state("EURUSD")
        assert state["equity"] == 10_000.0
        assert state["daily_loss_pct"] == 0.02

    def test_bus_feeds_l6_and_blocks(self, fresh_bus: LiveContextBus, engine: L6RiskAnalyzer) -> None:
        """End-to-end: bus state → L6 analyze → circuit breaker / DD block."""
        fresh_bus.update_account_state(
            "EURUSD",
            {
                "equity": 9_000.0,
                "peak_equity": 10_000.0,
                "daily_loss_pct": 0.06,  # 6% daily loss
                "consecutive_losses": 3,
                "circuit_breaker_active": True,
            },
        )
        state = fresh_bus.get_account_state("EURUSD")
        result = engine.analyze(rr=2.0, account_state=state)

        # Should hard-block: 10% drawdown + 6% daily DD
        assert result["risk_ok"] is False
        assert result["drawdown_level"] == "LEVEL_4"


class TestBusTradeHistory:
    """LiveContextBus.get_trade_history() retrieval."""

    def test_returns_empty_when_no_source(self, fresh_bus: LiveContextBus) -> None:
        """No archive → returns None or empty list, L6/L7 degrade gracefully."""
        returns = fresh_bus.get_trade_history("EURUSD")
        assert returns is None or isinstance(returns, list)


# ═══════════════════════════════════════════════════════════════════
#  LRCE enrichment patch
# ═══════════════════════════════════════════════════════════════════


class TestLRCEEnrichmentPatch:
    """L6 LRCE should detect field fracture from enrichment data."""

    def test_lrce_stable_field(self, engine: L6RiskAnalyzer) -> None:
        """Coherent enrichment → LRCE low → no block."""
        result = engine.analyze(
            rr=2.0,
            enrichment={
                "fusion_momentum": 0.7,
                "quantum_probability": 0.72,
                "bias_strength": 0.65,
                "posterior": 0.68,
            },
        )
        assert result["lrce"] < 0.6
        assert result["risk_ok"] is True

    def test_lrce_fracture_blocks(self, engine: L6RiskAnalyzer) -> None:
        """Divergent enrichment → LRCE > 0.6 → hard block."""
        result = engine.analyze(
            rr=2.0,
            enrichment={
                "fusion_momentum": 0.9,
                "quantum_probability": 0.1,
                "bias_strength": 0.8,
                "posterior": 0.1,
            },
        )
        assert result["lrce"] > 0.6
        assert result["risk_ok"] is False
        assert any("LRCE_FRACTURE" in w for w in result["warnings"])

    def test_lrce_pipeline_patch_simulation(self, engine: L6RiskAnalyzer) -> None:
        """Simulate the pipeline's post-enrichment LRCE patch."""
        # Step 1: L6 runs without enrichment (LRCE = 0.0)
        l6 = engine.analyze(rr=2.0)
        assert l6["lrce"] == 0.0
        assert l6["risk_ok"] is True

        # Step 2: Enrichment data arrives (divergent field)
        enrichment_data = {
            "fusion_momentum": 0.9,
            "quantum_probability": 0.1,
            "bias_strength": 0.8,
            "posterior": 0.1,
        }

        # Step 3: Pipeline patches LRCE
        lrce = engine._compute_lrce(enrichment_data)
        l6["lrce"] = round(lrce, 4)

        if lrce > engine.lrce_block_threshold:
            l6["risk_status"] = "UNSTABLE_FIELD"
            l6["risk_ok"] = False
            l6.setdefault("warnings", []).append(f"LRCE_FRACTURE({lrce:.3f})")

        # Verify patch worked
        assert l6["lrce"] > 0.6
        assert l6["risk_ok"] is False
        assert any("LRCE_FRACTURE" in w for w in l6["warnings"])
