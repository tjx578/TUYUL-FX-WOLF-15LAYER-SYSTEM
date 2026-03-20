"""Integration tests: DynamicPositionSizingEngine <- upstream engines -> L10.

Verifies the complete data flow:

    ┌─────────────────────────────────────────────────────────────────┐
    │  MonteCarloEngine ──-> win_probability, avg_win, avg_loss       │
    │  BayesianEngine   ──-> posterior_probability                    │
    │  VolClusterModel  ──-> risk_multiplier                          │
    │         │                                                       │
    │         ▼                                                       │
    │  DynamicPositionSizingEngine.calculate()                        │
    │         │                                                       │
    │         ▼  (output = data contract for L10)                     │
    │  PositionSizingResult.final_fraction -> max_risk_pct override   │
    │         │                                                       │
    │         ▼                                                       │
    │  RiskManager.evaluate(dynamic_risk_percent=final_fraction)      │
    │         │                                                       │
    │         ▼                                                       │
    │  RiskMultiplierAggregator.compute(vol_clustering_multiplier=)   │
    │         │                                                       │
    │         ▼                                                       │
    │  VerdictEngine._evaluate_kelly_edge_gate(kelly_edge_data)       │
    └─────────────────────────────────────────────────────────────────┘

Tests cover:
    - VolCluster -> DynamicPSE data contract
    - DynamicPSE -> RiskManager data contract
    - DynamicPSE -> RiskMultiplier data contract
    - DynamicPSE -> VerdictEngine Gate 11 data contract
    - Full pipeline: VolCluster -> PSE -> RiskManager -> VerdictEngine
    - Edge cases: negative edge flows through entire chain
    - Authority boundary: no execution side-effects in any engine
    - Deterministic: same inputs -> same outputs through entire chain
    - Backward compatibility: all new features optional

Authority: ANALYSIS + RISK ZONE integration.
           No execution logic tested here.
           Layer-12 is sole decision authority; tested for gate behavior only.
"""

from __future__ import annotations

import numpy as np

from constitution.verdict_engine import VerdictEngine
from engines.dynamic_position_sizing_engine import (
    DynamicPositionSizingEngine,
    PositionSizingResult,
)
from engines.volatility_clustering_model import (
    VolatilityClusteringModel,
)
from risk.risk_manager import RiskDecision, RiskManager
from risk.risk_multiplier import RiskMultiplierAggregator, RiskMultiplierResult

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _trade_returns(
    n: int = 200, win_rate: float = 0.60, seed: int = 42,
) -> list[float]:
    """Generate realistic trade history for integration testing."""
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(15.0, 60.0)))
        else:
            returns.append(float(rng.uniform(-40.0, -8.0)))
    return returns


def _pse_with_returns(
    returns: list[float],
    win_probability: float = 0.60,
    avg_win: float = 40.0,
    avg_loss: float = -25.0,
    posterior_probability: float = 0.65,
    volatility_multiplier: float = 1.0,
) -> PositionSizingResult:
    """Helper: run DynamicPSE with given returns."""
    engine = DynamicPositionSizingEngine()
    return engine.calculate(
        win_probability=win_probability,
        avg_win=avg_win,
        avg_loss=avg_loss,
        posterior_probability=posterior_probability,
        returns_history=returns,
        volatility_multiplier=volatility_multiplier,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT: VolCluster -> DynamicPSE
# ══════════════════════════════════════════════════════════════════════════════


class TestVolClusterToPSEContract:
    """Verify VolatilityClusteringModel output feeds DynamicPSE correctly."""

    def test_vol_cluster_risk_multiplier_accepted(self) -> None:
        """VolCluster.risk_multiplier is a valid volatility_multiplier input."""
        returns = _trade_returns(200)

        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        assert hasattr(vol_result, "risk_multiplier")
        assert isinstance(vol_result.risk_multiplier, float)
        assert vol_result.risk_multiplier > 0

        pse = DynamicPositionSizingEngine()
        sizing = pse.calculate(
            win_probability=0.60, avg_win=40.0, avg_loss=-25.0,
            posterior_probability=0.65,
            returns_history=returns,
            volatility_multiplier=vol_result.risk_multiplier,
        )

        assert isinstance(sizing, PositionSizingResult)
        assert 0.0 <= sizing.final_fraction <= 0.03

    def test_vol_cluster_high_persistence_reduces_size(self) -> None:
        """High volatility persistence -> higher multiplier -> smaller position.

        We compare a calm market (low vol returns) against a volatile market
        (high vol returns) to verify the chain dampens appropriately.
        """
        calm_returns = [float(np.random.default_rng(1).uniform(-5, 10)) for _ in range(200)]
        volatile_returns = [float(np.random.default_rng(2).uniform(-100, 100)) for _ in range(200)]

        vol_model = VolatilityClusteringModel()

        vol_calm = vol_model.analyze(calm_returns)
        vol_volatile = vol_model.analyze(volatile_returns)

        pse = DynamicPositionSizingEngine()
        base = {
            "win_probability": 0.60, "avg_win": 40.0, "avg_loss": -25.0,
            "posterior_probability": 0.65,
        }

        r_calm = pse.calculate(
            **base,
            returns_history=calm_returns,
            volatility_multiplier=vol_calm.risk_multiplier,
        )
        r_vol = pse.calculate(
            **base,
            returns_history=volatile_returns,
            volatility_multiplier=vol_volatile.risk_multiplier,
        )

        # Volatile market should get equal or smaller sizing
        assert r_vol.final_fraction <= r_calm.final_fraction + 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT: DynamicPSE -> RiskManager
# ══════════════════════════════════════════════════════════════════════════════


class TestPSEToRiskManagerContract:
    """Verify DynamicPSE output feeds RiskManager correctly."""

    def test_final_fraction_as_dynamic_risk(self) -> None:
        """PSE.final_fraction plugs directly into RiskManager.dynamic_risk_percent."""
        sizing = _pse_with_returns(_trade_returns(100))

        mgr = RiskManager(max_risk_percent=0.03)
        decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=0,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=sizing.final_fraction,
        )

        assert isinstance(decision, RiskDecision)
        assert decision.effective_risk_percent <= 0.03
        assert decision.risk_source in ("DYNAMIC_PSE", "DYNAMIC_CLAMPED")

    def test_zero_edge_blocks_in_risk_manager(self) -> None:
        """PSE with negative edge -> final_fraction=0 -> RiskManager blocks."""
        sizing = _pse_with_returns(
            _trade_returns(100),
            win_probability=0.20,
            avg_win=10.0,
            avg_loss=-50.0,
        )

        assert sizing.edge_negative is True
        assert sizing.final_fraction == 0.0

        mgr = RiskManager()
        decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=0,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=sizing.final_fraction,
        )

        assert decision.trade_allowed is False
        assert "DYNAMIC_RISK_ZERO_EDGE" in decision.violations

    def test_dynamic_risk_reduces_lot(self) -> None:
        """Dynamic sizing produces smaller lots than static maximum."""
        sizing = _pse_with_returns(
            _trade_returns(100),
            win_probability=0.60,
            posterior_probability=0.65,
            volatility_multiplier=1.5,
        )

        mgr = RiskManager(max_risk_percent=0.03)

        static_decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=0,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=None,  # static
        )
        dynamic_decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=0,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=sizing.final_fraction,
        )

        assert dynamic_decision.recommended_lot <= static_decision.recommended_lot


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT: DynamicPSE -> RiskMultiplierAggregator
# ══════════════════════════════════════════════════════════════════════════════


class TestPSEToRiskMultiplierContract:
    """Verify VolCluster.risk_multiplier -> RiskMultiplierAggregator -> PSE."""

    def test_vol_cluster_into_aggregator(self) -> None:
        """risk_multiplier feeds into aggregator's vol_clustering_multiplier slot."""
        returns = _trade_returns(200)

        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        agg = RiskMultiplierAggregator()
        mult_result = agg.compute(
            vol_clustering_multiplier=vol_result.risk_multiplier,
        )

        assert isinstance(mult_result, RiskMultiplierResult)
        assert mult_result.vol_clustering_multiplier == round(vol_result.risk_multiplier, 4)
        assert mult_result.composite >= 0

    def test_aggregator_composite_into_pse(self) -> None:
        """Aggregator composite feeds as PSE volatility_multiplier."""
        returns = _trade_returns(200)

        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        agg = RiskMultiplierAggregator()
        mult_result = agg.compute(
            macro_multiplier=1.1,
            vol_clustering_multiplier=vol_result.risk_multiplier,
            correlation_multiplier=1.05,
        )

        pse = DynamicPositionSizingEngine()
        sizing = pse.calculate(
            win_probability=0.60, avg_win=40.0, avg_loss=-25.0,
            posterior_probability=0.65,
            returns_history=returns,
            volatility_multiplier=mult_result.composite,
        )

        assert isinstance(sizing, PositionSizingResult)
        assert 0.0 <= sizing.final_fraction <= 0.03


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT: DynamicPSE -> VerdictEngine Gate 11
# ══════════════════════════════════════════════════════════════════════════════


class TestPSEToVerdictGate11Contract:
    """Verify DynamicPSE -> VerdictEngine Gate 11 data contract."""

    def test_positive_edge_passes_gate(self) -> None:
        """PSE with positive edge -> Gate 11 passes."""
        sizing = _pse_with_returns(_trade_returns(100))

        assert sizing.edge_negative is False

        verdict = VerdictEngine(config={"kelly_edge_gate_enabled": True})
        gate = verdict._evaluate_kelly_edge_gate(sizing.to_dict())

        assert gate["passed"] is True
        assert gate["kelly_raw"] == sizing.kelly_raw

    def test_negative_edge_blocks_gate(self) -> None:
        """PSE with negative edge -> Gate 11 hard-blocks."""
        sizing = _pse_with_returns(
            _trade_returns(100),
            win_probability=0.20,
            avg_win=10.0,
            avg_loss=-50.0,
        )

        assert sizing.edge_negative is True

        verdict = VerdictEngine(config={"kelly_edge_gate_enabled": True})
        gate = verdict._evaluate_kelly_edge_gate(sizing.to_dict())

        assert gate["passed"] is False
        assert gate["severity"] == "HARD_BLOCK"

    def test_to_dict_has_gate_required_keys(self) -> None:
        """PSE.to_dict() must contain all keys Gate 11 needs."""
        sizing = _pse_with_returns(_trade_returns(100))
        d = sizing.to_dict()

        # Gate 11 expects these keys:
        assert "edge_negative" in d
        assert "kelly_raw" in d
        assert "final_fraction" in d
        assert isinstance(d["edge_negative"], bool)
        assert isinstance(d["kelly_raw"], float)
        assert isinstance(d["final_fraction"], float)


# ══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    """End-to-end: VolCluster -> PSE -> RiskManager + Gate 11."""

    def test_full_chain_positive_edge(self) -> None:
        """Complete happy path through all components."""
        returns = _trade_returns(200, win_rate=0.63, seed=77)

        # Step 1: Volatility clustering
        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        # Step 2: Risk multiplier aggregation
        agg = RiskMultiplierAggregator()
        mult_result = agg.compute(
            vol_clustering_multiplier=vol_result.risk_multiplier,
        )

        # Step 3: Dynamic position sizing
        pse = DynamicPositionSizingEngine(max_risk_cap=0.03)
        sizing = pse.calculate(
            win_probability=0.63,
            avg_win=45.0,
            avg_loss=-25.0,
            posterior_probability=0.66,
            returns_history=returns,
            volatility_multiplier=mult_result.composite,
        )

        # Step 4: Risk manager evaluation
        mgr = RiskManager(max_risk_percent=0.03)
        decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=1,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=sizing.final_fraction,
        )

        # Step 5: Gate 11 check
        verdict = VerdictEngine(config={"kelly_edge_gate_enabled": True})
        gate = verdict._evaluate_kelly_edge_gate(sizing.to_dict())

        # Assertions: consistent positive flow
        assert sizing.edge_negative is False
        assert 0.0 < sizing.final_fraction <= 0.03
        assert decision.trade_allowed is True
        assert decision.recommended_lot > 0
        assert gate["passed"] is True

    def test_full_chain_negative_edge(self) -> None:
        """Complete rejection path: no edge -> all components agree NO_TRADE."""
        returns = _trade_returns(200, win_rate=0.25, seed=88)

        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        pse = DynamicPositionSizingEngine()
        sizing = pse.calculate(
            win_probability=0.25,
            avg_win=15.0,
            avg_loss=-50.0,
            posterior_probability=0.30,
            returns_history=returns,
            volatility_multiplier=vol_result.risk_multiplier,
        )

        mgr = RiskManager()
        decision = mgr.evaluate(
            account_balance=100_000.0,
            account_equity=100_000.0,
            daily_pnl=0.0,
            open_trade_count=0,
            stop_loss_pips=25.0,
            pip_value_per_lot=10.0,
            dynamic_risk_percent=sizing.final_fraction,
        )

        verdict = VerdictEngine(config={"kelly_edge_gate_enabled": True})
        gate = verdict._evaluate_kelly_edge_gate(sizing.to_dict())

        # All agree: no trade
        assert sizing.edge_negative is True
        assert sizing.final_fraction == 0.0
        assert decision.trade_allowed is False
        assert gate["passed"] is False


# ══════════════════════════════════════════════════════════════════════════════
# AUTHORITY BOUNDARY TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestAuthorityBoundary:
    """Verify no component violates constitutional authority boundaries."""

    def test_pse_has_no_execution_methods(self) -> None:
        """DynamicPSE MUST NOT have execution capabilities."""
        pse = DynamicPositionSizingEngine()
        forbidden = [
            "execute", "place_order", "open_trade", "close_trade",
            "send_order", "modify_order", "cancel_order",
        ]
        for method in forbidden:
            assert not hasattr(pse, method), f"PSE must not have '{method}'"

    def test_pse_has_no_market_direction(self) -> None:
        """DynamicPSE MUST NOT produce market direction signals."""
        pse = DynamicPositionSizingEngine()
        forbidden = ["direction", "signal", "buy", "sell", "long", "short"]
        for attr in forbidden:
            assert not hasattr(pse, attr), f"PSE must not have '{attr}'"

    def test_risk_manager_has_no_market_direction(self) -> None:
        """RiskManager MUST NOT decide market direction."""
        mgr = RiskManager()
        forbidden = ["direction", "signal", "buy", "sell", "long", "short"]
        for attr in forbidden:
            assert not hasattr(mgr, attr), f"RiskManager must not have '{attr}'"

    def test_result_has_no_direction_fields(self) -> None:
        """PositionSizingResult MUST NOT contain direction fields."""
        sizing = _pse_with_returns(_trade_returns(100))
        d = sizing.to_dict()

        forbidden_keys = {"direction", "signal", "side", "action"}
        assert not (forbidden_keys & set(d.keys()))


# ══════════════════════════════════════════════════════════════════════════════
# DETERMINISM TEST
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Verify entire chain is deterministic (no hidden RNG)."""

    def test_full_chain_deterministic(self) -> None:
        """Running full chain twice with same inputs -> identical output."""
        returns = _trade_returns(200, seed=55)

        def _run_chain() -> tuple[PositionSizingResult, RiskDecision, dict]:
            vol = VolatilityClusteringModel().analyze(returns)
            pse = DynamicPositionSizingEngine()
            sizing = pse.calculate(
                win_probability=0.63, avg_win=45.0, avg_loss=-25.0,
                posterior_probability=0.66,
                returns_history=returns,
                volatility_multiplier=vol.risk_multiplier,
            )
            mgr = RiskManager()
            decision = mgr.evaluate(
                account_balance=100_000.0,
                account_equity=100_000.0,
                daily_pnl=0.0,
                open_trade_count=0,
                stop_loss_pips=25.0,
                pip_value_per_lot=10.0,
                dynamic_risk_percent=sizing.final_fraction,
            )
            verdict = VerdictEngine(config={"kelly_edge_gate_enabled": True})
            gate = verdict._evaluate_kelly_edge_gate(sizing.to_dict())
            return sizing, decision, gate

        s1, d1, g1 = _run_chain()
        s2, d2, g2 = _run_chain()

        assert s1.final_fraction == s2.final_fraction
        assert s1.kelly_raw == s2.kelly_raw
        assert s1.cvar_value == s2.cvar_value
        assert d1.recommended_lot == d2.recommended_lot
        assert d1.effective_risk_percent == d2.effective_risk_percent
        assert g1["passed"] == g2["passed"]
