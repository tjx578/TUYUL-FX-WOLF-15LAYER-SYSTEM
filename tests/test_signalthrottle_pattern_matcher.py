from __future__ import annotations

from analysis.market_context_validator import MarketContext, validate_market_context
from analysis.signalthrottle_patterns import match_golden_patterns


def test_usdjpy_upper_absorption_blocks_buy_chase():
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

    assert result.selected_pattern_id == "UPPER_ABSORPTION_WARNING"
    assert result.pattern_tier == "S"
    assert result.pair_role == "PHASE_SENSITIVE_JPY_MAJOR"
    assert result.entry_permission == "NO_NEW_BUY"
    assert result.chase_allowed is False
    assert result.final_direction == "NO_NEW_ENTRY"
    assert result.pattern_match_score >= 80
    assert result.execution_readiness_score <= 69
    assert result.jpy_alignment_status == "UNKNOWN"
    assert result.alignment_missing_reason == "jpy_alignment,dual_theme_status"


def test_usdjpy_liquidation_expansion_keeps_sell_retest_only():
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

    assert result.selected_pattern_id == "LIQUIDATION_EXPANSION"
    assert result.entry_permission == "RETEST_ONLY"
    assert result.management_action == "SELL_AFTER_PULLBACK_NO_MARKET_CHASE"
    assert result.pattern_score >= 60
    assert result.action == "SELL_AFTER_PULLBACK_NO_MARKET_CHASE"


def test_sparse_archive_gets_low_score_and_no_trade_permission():
    result = match_golden_patterns(
        {
            "symbol": "USDJPY",
            "pressure_temperature": "SPARSE_ARCHIVE",
            "duration_seconds": 600,
            "event_count": 3,
            "density_per_minute": 0.3,
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "SPARSE_ARCHIVE"
    assert result["entry_permission"] == "NO_TRADE"
    assert result["pattern_score"] <= 39
    assert result["block_reason"] == "SPARSE_PRESSURE"


def test_jpy_theme_conflict_overrides_clean_block():
    result = match_golden_patterns(
        {
            "symbol": "CADJPY",
            "raw_direction": "SELL",
            "strategy_pattern": "CLEAN_BEARISH_CONTINUATION_PRESSURE",
            "theme_aligned": False,
            "jpy_alignment": "MIXED",
            "dual_theme_status": "CONFLICT",
            "duration_seconds": 360,
            "density_per_minute": 8.5,
        }
    )

    assert result["selected_pattern_id"] == "CLEAN_BLOCK_BUT_THEME_CONFLICT"
    assert result["entry_permission"] == "NO_TRADE"
    assert result["block_reason"] == "THEME_CONFLICT"
    assert "JPY_ALIGNMENT_REQUIRED" in result["matched_patterns"]


def test_metal_upper_spike_applies_short_hold_no_chase_policy():
    result = match_golden_patterns(
        {
            "symbol": "XAUUSD",
            "price_position": "MAIN_RESISTANCE",
            "duration_seconds": 330,
            "density_per_minute": 12.0,
            "range_position": 0.94,
        }
    )

    assert result["selected_pattern_id"] == "METAL_NO_CHASE_AFTER_UPPER_SPIKE"
    assert result["entry_permission"] == "NO_MARKET_CHASE"
    assert result["hold_policy"] == "SHORT_INTRADAY"
    assert result["management_action"] == "WAIT_PULLBACK_OR_RECLAIM"
