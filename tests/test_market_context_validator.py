from __future__ import annotations

from analysis.market_context_validator import MarketContext, missing_market_context_result, validate_market_context


def test_missing_market_context_never_validates_direction():
    result = missing_market_context_result("GBPCAD", "BUY")

    assert result.to_dict() == {
        "symbol": "GBPCAD",
        "raw_allowed_direction": "BUY",
        "final_direction": "WAIT",
        "direction_validated": False,
        "execution_grade": "UNVALIDATED",
        "action": "FETCH_MARKET_CONTEXT",
        "requires_market_context": True,
        "reason": (
            "missing_market_context=price_at_signal_start,price_at_5m_confirm,"
            "price_at_signal_end,m15_phase,h1_phase,theme_aligned,spread_normal"
        ),
    }


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


def test_theme_mismatch_blocks_candidate():
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

    assert result.direction_validated is False
    assert result.final_direction == "BLOCK_DIRECTION"
    assert result.action == "BLOCK_ENTRY"
