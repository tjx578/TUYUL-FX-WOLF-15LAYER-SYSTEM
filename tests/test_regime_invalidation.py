from __future__ import annotations

from analysis.market_context_validator import MarketContext
from analysis.outcome_memory import summarize_outcome_memory
from analysis.regime_invalidation import validate_regime_state


def test_regime_invalidation_blocks_obvious_opposing_phase():
    context = MarketContext(
        symbol="AUDCAD",
        raw_allowed_direction="BUY",
        price_at_signal_start=0.9000,
        price_at_5m_confirm=0.8990,
        price_at_signal_end=0.8980,
        m15_phase="BEARISH_BREAKDOWN",
        h1_phase="DOWNTREND",
        spread_normal=True,
    )

    result = validate_regime_state(symbol="AUDCAD", direction="BUY", market_context=context)

    assert result.invalidated is True
    assert result.status == "INVALIDATED"
    assert "M15_REGIME_OPPOSES_BUY" in result.blockers
    assert "H1_REGIME_OPPOSES_BUY" in result.blockers


def test_regime_invalidation_uses_outcome_memory_failure_cluster():
    memory = summarize_outcome_memory(
        [
            {"symbol": "NZDCHF", "direction": "SELL", "forward_mfe_pips": 1, "forward_mae_pips": 7},
            {"symbol": "NZDCHF", "direction": "SELL", "forward_mfe_pips": 0, "forward_mae_pips": 8},
            {"symbol": "NZDCHF", "direction": "SELL", "forward_mfe_pips": 2, "forward_mae_pips": 6},
        ],
        min_samples_for_memory=3,
    )

    result = validate_regime_state(
        symbol="NZDCHF",
        direction="SELL",
        outcome_memory_summary=memory,
    )

    assert result.invalidated is True
    assert "OUTCOME_MEMORY_FAILURE_CLUSTER" in result.blockers
