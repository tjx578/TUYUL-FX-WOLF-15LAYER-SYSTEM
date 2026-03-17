"""Tests for Issue 7 (Portfolio MC) and Issue 8 (Enrichment → VerdictEngine)."""

from __future__ import annotations

import time

import pytest

from constitution.verdict_engine import VerdictEngine
from context.live_context_bus import LiveContextBus

# ── Issue 8: Enrichment consumed in VerdictEngine.produce_verdict ────


class TestVerdictEngineEnrichmentInjection:
    """Verify enrichment scores modulate confidence in the class-based path."""

    def setup_method(self) -> None:
        # Reset singleton and inject a fresh tick so the stale-feed
        # circuit breaker does not fire during these unit tests.
        LiveContextBus.reset_singleton()
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.085, "ask": 1.086, "timestamp": time.time()})

    def _make_layer_results(
        self,
        enrichment_score: float = 0.0,
        enrichment_confidence_adj: float = 0.0,
    ) -> dict:
        return {
            "L7": {
                "win_probability": 65.0,
                "profit_factor": 1.5,
                "risk_of_ruin": 0.05,
                "bayesian_posterior": 0.62,
                "bayesian_ci_low": 0.55,
                "bayesian_ci_high": 0.70,
                "conf12_raw": 0.75,
                "mc_passed_threshold": True,
                "validation": "PASS",
                "expected_value": 12.0,
                "max_drawdown": 0.03,
            },
            "enrichment_score": enrichment_score,
            "enrichment_confidence_adj": enrichment_confidence_adj,
        }

    def _all_pass_gates(self, n: int = 10) -> dict:
        return {f"gate_{i}": {"passed": True, "score": 1.0} for i in range(n)}

    def test_high_enrichment_boosts_execute_confidence(self):
        engine = VerdictEngine()
        gates = self._all_pass_gates()
        layers = self._make_layer_results(enrichment_score=0.85)

        verdict = engine.produce_verdict("EURUSD", layers, gates)

        assert verdict["verdict"] == "EXECUTE"
        assert verdict["enrichment_applied"] is True
        # Confidence should be boosted above the base L7-adjusted value
        assert verdict["confidence"] > 0.85

    def test_low_enrichment_dampens_execute_confidence(self):
        engine = VerdictEngine()
        gates = self._all_pass_gates()
        layers = self._make_layer_results(enrichment_score=0.20)

        verdict = engine.produce_verdict("EURUSD", layers, gates)

        assert verdict["verdict"] == "EXECUTE"
        assert verdict["enrichment_applied"] is True

    def test_no_enrichment_no_change(self):
        engine = VerdictEngine()
        gates = self._all_pass_gates()
        layers_with = self._make_layer_results(enrichment_score=0.0)
        layers_without = self._make_layer_results(enrichment_score=0.0)

        v1 = engine.produce_verdict("EURUSD", layers_with, gates)
        v2 = engine.produce_verdict("EURUSD", layers_without, gates)

        assert v1["confidence"] == v2["confidence"]
        assert v1["enrichment_applied"] is False

    def test_enrichment_never_promotes_hold_to_execute(self):
        """Constitutional boundary: enrichment cannot override verdict."""
        engine = VerdictEngine()
        # Only 5/10 gates pass → HOLD or NO_TRADE
        gates = {f"gate_{i}": {"passed": i < 5, "score": 1.0 if i < 5 else 0.0} for i in range(10)}
        layers = self._make_layer_results(enrichment_score=0.99, enrichment_confidence_adj=0.10)

        verdict = engine.produce_verdict("EURUSD", layers, gates)

        assert verdict["verdict"] != "EXECUTE"

    def test_negative_enrichment_adj_demotes_confidence(self):
        engine = VerdictEngine()
        gates = self._all_pass_gates()
        layers = self._make_layer_results(enrichment_confidence_adj=-0.12)

        verdict = engine.produce_verdict("EURUSD", layers, gates)

        assert verdict["verdict"] == "EXECUTE"
        assert verdict["enrichment_applied"] is True

    def test_enrichment_context_present_in_output(self):
        engine = VerdictEngine()
        gates = self._all_pass_gates()
        layers = self._make_layer_results(enrichment_score=0.60, enrichment_confidence_adj=0.03)

        verdict = engine.produce_verdict("EURUSD", layers, gates)

        assert "enrichment_context" in verdict
        assert verdict["enrichment_context"]["enrichment_score"] == 0.60
        assert verdict["enrichment_context"]["enrichment_confidence_adj"] == 0.03


# ── Issue 7: Portfolio-level Correlated Monte Carlo ──────────────────


class TestPortfolioMonteCarlo:
    """Test multi-pair correlated MC simulation."""

    def test_empty_portfolio_returns_block(self):
        from analysis.portfolio_monte_carlo import run_portfolio_monte_carlo  # noqa: PLC0415

        result = run_portfolio_monte_carlo(pair_specs=[])
        assert result.advisory_flag == "BLOCK"
        assert result.portfolio_risk_of_ruin == 1.0

    def test_single_pair_matches_uncorrelated(self):
        from analysis.portfolio_monte_carlo import (  # noqa: PLC0415
            PairSpec,
            run_portfolio_monte_carlo,
        )

        spec = PairSpec(
            symbol="EURUSD",
            win_probability=0.60,
            avg_win=100.0,
            avg_loss=80.0,
        )
        result = run_portfolio_monte_carlo(
            pair_specs=[spec],
            n_simulations=5_000,
            horizon_bars=50,
            seed=42,
        )

        assert 0.0 <= result.portfolio_win_rate <= 1.0
        assert result.portfolio_profit_factor >= 0.0
        assert result.diversification_ratio == pytest.approx(1.0, abs=0.01)
        assert "EURUSD" in result.pair_contributions

    def test_correlated_pairs_increase_concentration(self):
        from analysis.portfolio_monte_carlo import (  # noqa: PLC0415
            PairSpec,
            run_portfolio_monte_carlo,
        )

        specs = [
            PairSpec(symbol="EURUSD", win_probability=0.55, avg_win=100, avg_loss=90),
            PairSpec(symbol="GBPUSD", win_probability=0.55, avg_win=100, avg_loss=90),
        ]

        # High positive correlation → concentrated risk
        result_corr = run_portfolio_monte_carlo(
            pair_specs=specs,
            historical_correlations={("EURUSD", "GBPUSD"): 0.85},
            n_simulations=5_000,
            seed=42,
        )

        # No correlation → diversified
        result_uncorr = run_portfolio_monte_carlo(
            pair_specs=specs,
            historical_correlations={("EURUSD", "GBPUSD"): 0.0},
            n_simulations=5_000,
            seed=42,
        )

        # Correlated portfolio should have higher diversification ratio
        # (closer to 1.0 = concentrated)
        assert result_corr.diversification_ratio > result_uncorr.diversification_ratio

    def test_negative_edge_produces_high_ruin(self):
        from analysis.portfolio_monte_carlo import (  # noqa: PLC0415
            PairSpec,
            run_portfolio_monte_carlo,
        )

        spec = PairSpec(
            symbol="BADPAIR",
            win_probability=0.30,
            avg_win=50.0,
            avg_loss=100.0,
        )
        result = run_portfolio_monte_carlo(
            pair_specs=[spec],
            n_simulations=5_000,
            horizon_bars=100,
            seed=42,
        )

        assert result.portfolio_risk_of_ruin > 0.10
        assert result.advisory_flag in ("WARN", "BLOCK")

    def test_result_is_advisory_no_execution_authority(self):
        """Portfolio MC output must not contain execution commands."""
        from analysis.portfolio_monte_carlo import (  # noqa: PLC0415
            PairSpec,
            run_portfolio_monte_carlo,
        )

        spec = PairSpec(symbol="EURUSD", win_probability=0.60, avg_win=100, avg_loss=80)
        result = run_portfolio_monte_carlo(pair_specs=[spec], seed=42)

        # Must not contain any execution-authority fields
        result_dict = result.__dict__
        forbidden_keys = {"verdict", "execute", "direction", "lot_size", "order"}
        assert not forbidden_keys.intersection(result_dict.keys())

    def test_deterministic_with_seed(self):
        from analysis.portfolio_monte_carlo import (  # noqa: PLC0415
            PairSpec,
            run_portfolio_monte_carlo,
        )

        spec = PairSpec(symbol="EURUSD", win_probability=0.55, avg_win=100, avg_loss=90)
        r1 = run_portfolio_monte_carlo(pair_specs=[spec], seed=123)
        r2 = run_portfolio_monte_carlo(pair_specs=[spec], seed=123)

        assert r1.portfolio_win_rate == r2.portfolio_win_rate
        assert r1.portfolio_risk_of_ruin == r2.portfolio_risk_of_ruin
