"""Integration test: DynamicPositionSizingEngine → L10 position sizing.

Verifies the complete upstream chain:
    Monte Carlo → Bayesian → VolClustering → DynamicPSE → L10-compatible output

This tests the DATA CONTRACT, not the actual L10 pipeline wiring
(which belongs to pipeline/ integration tests).

Authority boundary check:
    - DynamicPSE outputs a risk_percent recommendation
    - L10 accepts it as max_risk_pct override
    - Neither module executes trades or overrides L12
"""

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]

from engines.dynamic_position_sizing_engine import (
    DynamicPositionSizingEngine,
)
from engines.volatility_clustering_model import VolatilityClusteringModel


def _trade_returns(n: int = 150, win_rate: float = 0.60, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(15.0, 60.0)))
        else:
            returns.append(float(rng.uniform(-40.0, -8.0)))
    return returns


class TestL10KellyIntegration:
    """Verify DynamicPSE output is compatible with L10 consumption."""

    def test_vol_cluster_to_pse_pipeline(self) -> None:
        """VolatilityClusteringModel feeds risk_multiplier into DynamicPSE."""
        returns = _trade_returns(200)

        # Step 1: Volatility clustering analysis
        vol_model = VolatilityClusteringModel()
        vol_result = vol_model.analyze(returns)

        # Step 2: Feed into position sizing
        pse = DynamicPositionSizingEngine()
        sizing_result = pse.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-25.0,
            posterior_probability=0.65,
            returns_history=returns,
            volatility_multiplier=vol_result.risk_multiplier,
        )

        # Verify output contract for L10
        assert isinstance(sizing_result.final_fraction, float)
        assert 0.0 <= sizing_result.final_fraction <= 0.03
        assert isinstance(sizing_result.risk_percent, float)
        assert sizing_result.risk_percent == round(sizing_result.final_fraction * 100, 2)

    def test_l10_contract_fields(self) -> None:
        """DynamicPSE result must contain all fields L10 needs."""
        pse = DynamicPositionSizingEngine()
        result = pse.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-25.0,
            posterior_probability=0.65,
            returns_history=_trade_returns(100),
            volatility_multiplier=1.0,
        )

        d = result.to_dict()

        # L10 needs these fields:
        assert "final_fraction" in d       # max_risk_pct override
        assert "risk_percent" in d         # display value
        assert "max_risk_cap" in d         # prop-firm cap context
        assert "edge_negative" in d        # whether to trade at all
        assert "kelly_fraction" in d       # transparency
        assert "payoff_ratio" in d         # RR context

    def test_edge_negative_prevents_trade(self) -> None:
        """When Kelly edge is negative, L10 should receive size=0."""
        pse = DynamicPositionSizingEngine()
        result = pse.calculate(
            win_probability=0.25,
            avg_win=20.0,
            avg_loss=-50.0,
            posterior_probability=0.5,
            returns_history=_trade_returns(100),
            volatility_multiplier=1.0,
        )

        assert result.edge_negative is True
        assert result.final_fraction == 0.0
        # L10 should interpret final_fraction == 0 as NO_TRADE_SIZE

    def test_authority_boundary(self) -> None:
        """DynamicPSE MUST NOT contain execution methods or market direction."""
        pse = DynamicPositionSizingEngine()

        # No execution methods
        assert not hasattr(pse, "execute")
        assert not hasattr(pse, "place_order")
        assert not hasattr(pse, "open_trade")

        # No market direction
        assert not hasattr(pse, "direction")
        assert not hasattr(pse, "signal")
        assert not hasattr(pse, "buy")
        assert not hasattr(pse, "sell")

    def test_deterministic_output(self) -> None:
        """Same inputs must produce identical output (no RNG)."""
        pse = DynamicPositionSizingEngine()
        params = {
            "win_probability": 0.60,
            "avg_win": 40.0,
            "avg_loss": -25.0,
            "posterior_probability": 0.65,
            "returns_history": _trade_returns(100),
            "volatility_multiplier": 1.2,
        }

        r1 = pse.calculate(**params) # type: ignore
        r2 = pse.calculate(**params) # pyright: ignore[reportArgumentType]

        assert r1.final_fraction == r2.final_fraction
        assert r1.kelly_raw == r2.kelly_raw
        assert r1.cvar_value == r2.cvar_value
