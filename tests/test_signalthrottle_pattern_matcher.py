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


def test_gbpjpy_bullish_microburst_requires_jpy_alignment_metadata():
    result = match_golden_patterns(
        {
            "symbol": "GBPJPY",
            "raw_direction": "BUY",
            "duration_seconds": 286,
            "density_per_minute": 10.68,
            "m15_phase": "BULLISH",
            "h1_phase": "BULLISH",
            "h4_phase": "MIXED",
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "MICROBURST_FOLLOWTHROUGH_RECLAIM"
    assert result["pattern_tier"] == "S-"
    assert result["pair_role"] == "PHASE_SENSITIVE_JPY_CROSS"
    assert result["entry_permission"] == "BUY_RECLAIM_OR_PULLBACK_HOLD"
    assert result["management_action"] == "NO_MARKET_CHASE_CONFIRM_THEME"
    assert "JPY_ALIGNMENT_REQUIRED" in result["matched_patterns"]
    assert result["alignment_missing_reason"] is None


def test_universal_microburst_followthrough_can_match_another_jpy_cross():
    result = match_golden_patterns(
        {
            "symbol": "EURJPY",
            "raw_direction": "BUY",
            "duration_seconds": 286,
            "density_per_minute": 10.68,
            "m15_phase": "BULLISH",
            "h1_phase": "BULLISH",
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "MICROBURST_FOLLOWTHROUGH_RECLAIM"
    assert result["golden_reference"] == "GBPJPY/AUDJPY"
    assert result["pattern_scope"] == "UNIVERSAL"
    assert result["applies_to"] == "ALL_PAIRS_IF_CONDITIONS_MATCH"
    assert result["golden_references"] == ["GBPJPY", "AUDJPY"]
    assert result["pair_role"] == "JPY_BASKET_GOLDEN_REFERENCE"
    assert "JPY_ALIGNMENT_REQUIRED" in result["matched_patterns"]


def test_liquidation_reclaim_required_is_universal_eurjpy_reference():
    result = match_golden_patterns(
        {
            "symbol": "EURJPY",
            "raw_direction": "BUY",
            "event_count": 42,
            "density_per_minute": 6.0,
            "h4_atr_ratio": 7.22,
            "h4_close_pos": 0.155,
            "reclaim_confirmed": False,
            "price_confirmation": False,
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
        }
    )

    assert result["selected_pattern_id"] == "LIQUIDATION_RECLAIM_REQUIRED"
    assert result["pattern_scope"] == "UNIVERSAL"
    assert result["golden_references"] == ["EURJPY"]
    assert result["entry_permission"] == "WATCH_ONLY_UNTIL_RECLAIM"
    assert result["block_reason"] == "LIQUIDATION_RECLAIM_REQUIRED"


def test_liquidation_reclaim_required_can_match_non_eurjpy_pair():
    result = match_golden_patterns(
        {
            "symbol": "XAUUSD",
            "raw_direction": "BUY",
            "event_count": 70,
            "density_per_minute": 9.0,
            "structure_atr_ratio": 4.2,
            "structure_close_pos": 0.12,
            "reclaim_confirmed": False,
            "price_confirmation": False,
        }
    )

    assert result["selected_pattern_id"] == "LIQUIDATION_RECLAIM_REQUIRED"
    assert result["golden_reference"] == "EURJPY"
    assert result["pair_role"] == "METAL_VOLATILITY_LIFECYCLE"


def test_theme_context_only_is_selection_boost_not_execution_signal():
    result = match_golden_patterns(
        {
            "symbol": "CADCHF",
            "raw_direction": "SELL",
            "theme_context_only": True,
            "lower_timeframe_confirmation": False,
            "price_confirmation": False,
            "theme_aligned": True,
        }
    )

    assert result["selected_pattern_id"] == "THEME_CONTEXT_ONLY_NOT_STANDALONE"
    assert result["entry_permission"] == "PAIR_SELECTION_BOOST_ONLY"
    assert result["management_action"] == "WAIT_PRICE_CONTEXT"
    assert result["pattern_score"] <= 69


def test_mid_range_continuation_requires_pullback_when_chase_rr_is_poor():
    result = match_golden_patterns(
        {
            "symbol": "EURJPY",
            "raw_direction": "BUY",
            "h4_atr_ratio": 1.2,
            "h4_close_pos": 0.989,
            "forward_mfe_pips": 49.2,
            "forward_mae_pips": -54.7,
            "structure_candle_strong_close": True,
            "chase_rr_poor": True,
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
        }
    )

    assert result["selected_pattern_id"] == "MID_RANGE_CONTINUATION_PULLBACK_REQUIRED"
    assert result["entry_permission"] == "PULLBACK_OR_RECLAIM_ONLY"
    assert result["management_action"] == "NO_CHASE"
    assert result["block_reason"] == "MID_RANGE_PULLBACK_REQUIRED"


def test_gbpjpy_clean_five_minute_block_stays_watch_only():
    result = match_golden_patterns(
        {
            "symbol": "GBPJPY",
            "raw_direction": "BUY",
            "duration_seconds": 322,
            "density_per_minute": 10.05,
            "m15_phase": "BULLISH",
            "h1_phase": "BULLISH",
            "h4_phase": "MIXED",
            "price_position": "MAIN_RESISTANCE",
            "theme_aligned": True,
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "CLEAN_5M_TIMING_GATE_NOT_FINAL"
    assert result["entry_permission"] == "ENTRY_WATCH_ONLY_WAIT_RECLAIM"
    assert result["pattern_score"] <= 69
    assert result["jpy_alignment_status"] == "UNKNOWN"
    assert result["alignment_missing_reason"] == "jpy_alignment,dual_theme_status"


def test_gbpjpy_high_density_bearish_context_blocks_buy_chase():
    result = match_golden_patterns(
        {
            "symbol": "GBPJPY",
            "raw_direction": "BUY",
            "duration_seconds": 886,
            "density_per_minute": 12.12,
            "m15_phase": "MIXED",
            "h1_phase": "BEARISH",
            "h4_phase": "BEARISH",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE"
    assert result["entry_permission"] == "NO_CHASE_PROTECT_OR_WAIT_RETEST"
    assert result["block_reason"] == "HIGH_DENSITY_CONTEXT_NO_CHASE"
    assert result["pattern_score"] <= 69


def test_nzdchf_hot_block_in_bearish_context_prefers_sell_management():
    result = match_golden_patterns(
        {
            "symbol": "NZDCHF",
            "raw_direction": "BUY",
            "duration_seconds": 321,
            "density_per_minute": 11.39,
            "m15_phase": "BEARISH",
            "h1_phase": "MIXED",
            "d1_phase": "BULLISH",
            "price_fails_reclaim": True,
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "BEARISH_OR_BULLISH_CONTINUATION_AFTER_HOT_BLOCK"
    assert result["pair_role"] == "CHF_CROSS_PHASE_SENSITIVE"
    assert result["entry_permission"] == "PHASE_CONTINUATION_RETEST_OR_PROTECT"
    assert result["management_action"] == "FOLLOW_PHASE_RETEST_OR_PROTECT"


def test_nzdchf_repeated_microburst_is_reclaim_watch_not_final_reversal():
    result = match_golden_patterns(
        {
            "symbol": "NZDCHF",
            "raw_direction": "BUY",
            "duration_seconds": 266,
            "density_per_minute": 12.65,
            "phase_unpriced": "REPEATED_MICROBOOST",
            "m15_phase": "BEARISH",
            "h1_phase": "MIXED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL"
    assert result["entry_permission"] == "RECLAIM_WATCH_OR_PARTIAL_EXIT"
    assert result["pattern_score"] <= 79


def test_nzdchf_repeated_pressure_with_daily_conflict_is_management_alert():
    result = match_golden_patterns(
        {
            "symbol": "NZDCHF",
            "raw_direction": "BUY",
            "duration_seconds": 600,
            "density_per_minute": 9.5,
            "repeated_pressure": True,
            "m15_phase": "BEARISH",
            "h1_phase": "MIXED",
            "d1_phase": "BULLISH",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "REPEATED_PRESSURE_MANAGEMENT_ALERT"
    assert result["entry_permission"] == "WAIT_BREAK_OR_RECLAIM"
    assert result["management_action"] == "MANAGEMENT_ALERT"
    assert result["pattern_score"] <= 69


def test_audjpy_jpy_weakness_open_lane_requires_alignment_and_reclaim_context():
    result = match_golden_patterns(
        {
            "symbol": "AUDJPY",
            "raw_direction": "BUY",
            "duration_seconds": 900,
            "density_per_minute": 5.73,
            "m15_phase": "RECLAIM",
            "h1_phase": "BULLISH",
            "h4_phase": "BULLISH",
            "d1_phase": "BULLISH",
            "price_position": "MID_RANGE",
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "OPEN_LANE_TIMING_VALID"
    assert result["pattern_tier"] == "S"
    assert result["pair_role"] == "JPY_WEAKNESS_CONFIRMATION_CROSS"
    assert result["entry_permission"] == "ENTRY_WATCH"
    assert "JPY_ALIGNMENT_REQUIRED" in result["matched_patterns"]
    assert result["alignment_missing_reason"] is None


def test_audjpy_high_density_pullback_then_expand_is_entry_watch():
    result = match_golden_patterns(
        {
            "symbol": "AUDJPY",
            "raw_direction": "BUY",
            "duration_seconds": 480,
            "density_per_minute": 10.2,
            "m15_phase": "PULLBACK",
            "h1_phase": "BULLISH",
            "h4_phase": "BULLISH",
            "m15_close_pos": 0.06,
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "MICROBURST_FOLLOWTHROUGH_RECLAIM"
    assert result["pattern_tier"] == "S-"
    assert result["entry_permission"] == "BUY_RECLAIM_OR_PULLBACK_HOLD"


def test_audjpy_late_upper_density_blocks_chase():
    result = match_golden_patterns(
        {
            "symbol": "AUDJPY",
            "raw_direction": "BUY",
            "duration_seconds": 840,
            "density_per_minute": 8.1,
            "block_delta_pips": 11.7,
            "m15_phase": "BULLISH",
            "h1_phase": "BULLISH",
            "h4_phase": "MIXED",
            "d1_phase": "MIXED_BEARISH",
            "price_position": "MAIN_RESISTANCE",
            "theme_aligned": True,
            "jpy_alignment": "ALIGNED",
            "dual_theme_status": "ALIGNED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE"
    assert result["entry_permission"] == "NO_CHASE_PROTECT_OR_WAIT_RETEST"
    assert result["block_reason"] == "HIGH_DENSITY_CONTEXT_NO_CHASE"
    assert result["pattern_score"] <= 69


def test_eurchf_mature_microboost_requires_reclaim():
    result = match_golden_patterns(
        {
            "symbol": "EURCHF",
            "raw_direction": "BUY",
            "duration_seconds": 196,
            "density_per_minute": 12.88,
            "phase_unpriced": "MATURE_MICROBOOST",
            "first_60m_failed": True,
            "m15_phase": "MIXED",
            "h1_phase": "MIXED",
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL"
    assert result["pair_role"] == "CHF_WEAKNESS_MICROBOOST_CROSS"
    assert result["entry_permission"] == "RECLAIM_WATCH_OR_PARTIAL_EXIT"
    assert result["pattern_score"] <= 69


def test_eurchf_chf_weakness_is_delayed_watch_after_early_failure():
    result = match_golden_patterns(
        {
            "symbol": "EURCHF",
            "raw_direction": "BUY",
            "duration_seconds": 900,
            "density_per_minute": 7.4,
            "m15_phase": "BEARISH",
            "h1_phase": "MIXED",
            "h4_phase": "BULLISH",
            "d1_phase": "BULLISH",
            "close_60m_pips": -6.9,
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "DELAYED_FOLLOWTHROUGH_WATCH"
    assert result["pattern_tier"] == "A-"
    assert result["entry_permission"] == "DELAYED_WATCH"
    assert result["management_action"] == "WAIT_SUPPORT_HOLD_OR_RECLAIM"


def test_eurchf_upper_microboost_exhaustion_blocks_buy_chase():
    result = match_golden_patterns(
        {
            "symbol": "EURCHF",
            "raw_direction": "BUY",
            "duration_seconds": 900,
            "density_per_minute": 12.0,
            "phase_unpriced": "DENSE_MICROBOOST",
            "m15_phase": "BEARISH",
            "price_position": "MAIN_RESISTANCE",
            "m15_close_pos": 0.17,
            "spread_normal": True,
        }
    )

    assert result["selected_pattern_id"] == "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE"
    assert result["entry_permission"] == "NO_CHASE_PROTECT_OR_WAIT_RETEST"
    assert result["block_reason"] == "HIGH_DENSITY_CONTEXT_NO_CHASE"
    assert result["pattern_score"] <= 69


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
