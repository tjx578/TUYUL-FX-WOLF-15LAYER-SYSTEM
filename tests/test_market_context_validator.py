from __future__ import annotations

from analysis.market_context_validator import (
    MarketContext,
    missing_market_context_result,
    validate_execution_context,
    validate_market_context,
    validate_radar_context,
)


def test_missing_market_context_never_validates_direction():
    result = missing_market_context_result("GBPCAD", "BUY")
    payload = result.to_dict()

    expected = {
        "symbol": "GBPCAD",
        "raw_allowed_direction": "BUY",
        "final_direction": "WAIT",
        "direction_validated": False,
        "execution_grade": "UNVALIDATED",
        "action": "FETCH_MARKET_CONTEXT",
        "requires_market_context": True,
        "reason": (
            "missing_market_context=price_at_signal_start,price_at_5m_confirm,"
            "price_at_signal_end,m15_phase,h1_phase,spread_normal"
        ),
        "strategy_pattern": "PRICE_PHASE_UNRESOLVED",
        "phase_grade": "UNRESOLVED",
        "execution_side": "WAIT",
        "priority": "WATCH_NEUTRAL",
        "waiting_for": "M15_H1_PHASE_AND_STRUCTURE_CONFIRMATION",
        "requires_confirmation": True,
    }
    assert {key: payload[key] for key in expected} == expected
    assert payload["selected_pattern_id"] is None
    assert payload["pattern_score"] == 0


def test_radar_context_partial_does_not_require_m15_execution_fields():
    result = validate_radar_context(
        MarketContext(
            symbol="USDJPY",
            raw_allowed_direction=None,
            price_position="MAIN_RESISTANCE",
            h4_phase="DISTRIBUTION_BREAKDOWN",
            key_resistance=160.20,
        )
    )

    payload = result.to_dict()
    assert payload["radar_context_ready"] is True
    assert payload["execution_context_ready"] is False
    assert payload["valid_for_execution"] is False
    assert payload["requires_m15_close_policy"] == "NOT_APPLICABLE"
    assert "m15_phase" in payload["missing_execution_fields"]


def test_execution_context_alias_stays_strict_for_missing_fields():
    result = validate_execution_context(
        MarketContext(
            symbol="USDJPY",
            raw_allowed_direction="SELL",
            price_position="MAIN_RESISTANCE",
            h4_phase="DISTRIBUTION_BREAKDOWN",
        )
    )

    assert result.direction_validated is False
    assert result.action == "FETCH_MARKET_CONTEXT"
    assert "m15_phase" in result.reason


def test_buy_validates_only_when_price_theme_phase_align():
    result = validate_market_context(
        MarketContext(
            symbol="GBPCAD",
            raw_allowed_direction="BUY",
            price_at_signal_start=1.8500,
            price_at_5m_confirm=1.8520,
            price_at_signal_end=1.8550,
            m15_phase="PIVOT_RECLAIM",
            h1_phase="BULLISH",
            theme_aligned=True,
            spread_normal=True,
        )
    )

    assert result.direction_validated is True
    assert result.final_direction == "BUY"
    assert result.action == "BUY_ON_PULLBACK"


def test_sell_validates_only_when_price_theme_phase_align():
    result = validate_market_context(
        MarketContext(
            symbol="EURJPY",
            raw_allowed_direction="SELL",
            price_at_signal_start=168.20,
            price_at_5m_confirm=168.00,
            price_at_signal_end=167.80,
            m15_phase="BREAKDOWN_RETEST",
            h1_phase="DOWNTREND",
            theme_aligned=True,
            spread_normal=True,
        )
    )

    assert result.direction_validated is True
    assert result.final_direction == "SELL"
    assert result.action == "SELL_ON_PULLBACK"


def test_late_pressure_becomes_protect_not_entry():
    result = validate_market_context(
        MarketContext(
            symbol="NZDJPY",
            raw_allowed_direction="BUY",
            price_at_signal_start=91.00,
            price_at_5m_confirm=91.20,
            price_at_signal_end=91.40,
            m15_phase="PIVOT_RECLAIM",
            h1_phase="BULLISH",
            theme_aligned=True,
            spread_normal=True,
            is_late_pressure=True,
        )
    )

    assert result.direction_validated is False
    assert result.final_direction == "NO_NEW_ENTRY"
    assert result.execution_grade == "PROTECT"
    assert result.action == "PROTECT_PROFIT"


def test_theme_mismatch_does_not_block_price_phase_candidate():
    result = validate_market_context(
        MarketContext(
            symbol="GBPCAD",
            raw_allowed_direction="BUY",
            price_at_signal_start=1.8500,
            price_at_5m_confirm=1.8520,
            price_at_signal_end=1.8550,
            m15_phase="PIVOT_RECLAIM",
            h1_phase="BULLISH",
            theme_aligned=False,
            spread_normal=True,
        )
    )

    assert result.direction_validated is True
    assert result.final_direction == "BUY"
    assert result.action == "BUY_ON_PULLBACK"


def test_basket_contradiction_blocks_price_phase_candidate():
    result = validate_market_context(
        MarketContext(
            symbol="AUDCAD",
            raw_allowed_direction="BUY",
            price_at_signal_start=0.8900,
            price_at_5m_confirm=0.8920,
            price_at_signal_end=0.8940,
            m15_phase="PIVOT_RECLAIM",
            h1_phase="BULLISH",
            theme_aligned=True,
            spread_normal=True,
            base_basket_score=-0.82,
            quote_basket_score=0.15,
            pair_direction_alignment=-0.97,
            basket_blockers=["BASE_AUD_BASKET_WEAK", "QUOTE_CAD_BASKET_STRONG"],
        )
    )

    assert result.direction_validated is False
    assert result.final_direction == "WAIT"
    assert result.execution_grade == "BLOCKED"
    assert result.action == "BLOCK_BASKET_CONTRADICTION"
    assert result.reason == "basket_contradiction=BASE_AUD_BASKET_WEAK,QUOTE_CAD_BASKET_STRONG"


def test_buy_pressure_at_upper_resistance_becomes_protect_not_entry():
    result = validate_market_context(
        MarketContext(
            symbol="USDJPY",
            raw_allowed_direction="BUY",
            price_at_signal_start=159.775,
            price_at_5m_confirm=159.770,
            price_at_signal_end=159.769,
            m15_phase="PIVOT_RECLAIM",
            h1_phase="BULLISH",
            theme_aligned=True,
            spread_normal=True,
            price_position="MAIN_RESISTANCE",
            m15_rejection_from_resistance=True,
        )
    )

    assert result.direction_validated is False
    assert result.final_direction == "NO_NEW_ENTRY"
    assert result.strategy_pattern == "UPPER_RANGE_EXHAUSTION"
    assert result.execution_side == "PROTECT_LONG_OR_SELL_REJECTION"
    assert result.action == "NO_NEW_BUY_WAIT_SELL_OR_PULLBACK_CONFIRMATION"


def test_bearish_breakdown_cascade_validates_sell_context():
    result = validate_market_context(
        MarketContext(
            symbol="USDJPY",
            raw_allowed_direction="SELL",
            price_at_signal_start=160.683,
            price_at_5m_confirm=160.474,
            price_at_signal_end=159.999,
            m15_phase="SUPPORT_BREAK",
            h1_phase="DOWNTREND",
            h4_phase="DISTRIBUTION_BREAKDOWN",
            theme_aligned=True,
            spread_normal=True,
            price_position="LOWER_RANGE",
            m15_close_below_support=True,
        )
    )

    assert result.direction_validated is True
    assert result.final_direction == "SELL"
    assert result.strategy_pattern == "BEARISH_BREAKDOWN_CASCADE"
    assert result.priority == "WATCH_HIGH_SELL"
    assert result.action == "SELL_RETEST_OR_BREAKDOWN_CONTINUATION"


def test_liquidation_expansion_sells_after_pullback_not_chase():
    result = validate_market_context(
        MarketContext(
            symbol="USDJPY",
            raw_allowed_direction="SELL",
            price_at_signal_start=159.205,
            price_at_5m_confirm=159.052,
            price_at_signal_end=159.052,
            m15_phase="SUPPORT_BREAK",
            h1_phase="DOWNTREND",
            h4_phase="DISTRIBUTION_BREAKDOWN",
            theme_aligned=True,
            spread_normal=True,
            price_position="LOWER_RANGE",
            m15_close_below_support=True,
            m15_range_atr_ratio=3.49,
        )
    )

    assert result.direction_validated is True
    assert result.final_direction == "SELL"
    assert result.strategy_pattern == "BEARISH_LIQUIDATION_EXPANSION"
    assert result.action == "SELL_AFTER_PULLBACK_NO_MARKET_CHASE"
