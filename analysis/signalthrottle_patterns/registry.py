"""Static Golden Pattern Database v1 for SignalThrottle analysis.

The registry is deliberately analysis-only.  It describes known market-pattern
archetypes and pair roles, but it never executes trades and never bypasses L12.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GoldenPattern:
    pattern_id: str
    tier: str
    family: str
    golden_source: str
    function: str
    entry_permission: str
    management_action: str | None = None
    hold_policy: str | None = None
    chase_allowed: bool = False
    block_reason: str | None = None
    scope: str = "UNIVERSAL"
    applies_to: str = "ALL_PAIRS_IF_CONDITIONS_MATCH"
    golden_references: tuple[str, ...] = ()
    pair_specific_calibration: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.golden_references and self.golden_source:
            payload["golden_references"] = tuple(
                item.strip()
                for item in self.golden_source.replace("+", "/").split("/")
                if item.strip()
            )
        return payload


GOLDEN_PATTERNS: tuple[GoldenPattern, ...] = (
    GoldenPattern("OPEN_LANE_TIMING_VALID", "S", "TREND_LIFECYCLE", "GBPCAD/AUDJPY", "early entry-watch before expansion", "ENTRY_WATCH", chase_allowed=False, golden_references=("GBPCAD", "AUDJPY")),
    GoldenPattern("ZERO_DRAWDOWN_FOLLOWTHROUGH", "S", "OUTCOME_VALIDATION", "GBPCAD", "outcome quality upgrade", "TRACK_ONLY"),
    GoldenPattern("PRE_IGNITION_COUNTERFLOW_TRAP", "S", "DIRECTION_VALIDATION", "GBPCAD", "block provisional counterflow", "NO_TRADE", block_reason="COUNTERFLOW_FALSE_SIGNAL"),
    GoldenPattern("HIGH_DENSITY_ACCELERATION", "A", "TREND_LIFECYCLE", "GBPCAD", "continuation confirmation while price expands", "RETEST_ONLY", "HOLD_OR_ADD_SMALL_ON_RETEST"),
    GoldenPattern("LATE_DENSE_CONGESTION", "A", "LATE_STAGE_MANAGEMENT", "GBPCAD", "late density means protect/no chase", "NO_NEW_ENTRY", "PROTECT_PROFIT_TRAIL_TIGHT"),
    GoldenPattern("LATE_MICROBOOST_DECISION_POINT", "A", "LATE_STAGE_MANAGEMENT", "GBPCAD", "late microboost branch point", "NO_NEW_CHASE", "WAIT_NEXT_M15_CLOSE"),
    GoldenPattern("DELAYED_IGNITION_MICROBOOST", "A", "MICROBOOST_TO_EXPANSION", "EURCAD", "hot microboost before delayed expansion", "NOT_YET"),
    GoldenPattern("LATE_UPPER_MICROBOOST", "A", "LATE_STAGE_MANAGEMENT", "AUDCAD", "upper-range microboost after expansion", "NO_NEW_CHASE", "TRAIL_OR_WAIT_PULLBACK"),
    GoldenPattern("SATURATION_MICROBOOST_WARNING", "A", "EXHAUSTION_MANAGEMENT", "AUDCAD", "late follow-through failure warning", "BLOCK_NEW_ENTRY", "PROTECT_OR_WAIT_NEXT_M15"),
    GoldenPattern("MIRROR_BASKET_CONFIRMATION", "S", "THEME_BASKET", "NZDCAD+CADCHF+CADJPY", "theme confirmation via mirror pairs", "BOOST_THEME_NOT_AUTO_ENTRY"),
    GoldenPattern("SECONDARY_OPEN_LANE_CONFIRMATION", "A", "THEME_CONFIRMATION", "NZDCAD", "secondary timing support for primary pair", "CONDITIONAL_ONLY"),
    GoldenPattern("INVERSE_MIRROR_BREAKDOWN", "S", "INVERSE_CONFIRMATION", "CADCHF", "CAD-base breakdown confirms CAD weakness", "OWN_SIGNAL_REQUIRED"),
    GoldenPattern("CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY", "A", "EXECUTION_FILTER", "NZDCAD/CADCHF", "confirmation pair requires own trigger", "WAIT_OWN_TRIGGER"),
    GoldenPattern("LATE_SECONDARY_SATURATION", "A", "LATE_STAGE_MANAGEMENT", "NZDCAD", "secondary pair late no-chase", "NO_NEW_CHASE", "PROTECT_OR_WAIT_PULLBACK"),
    GoldenPattern("INVERSE_COOLING_PAUSE", "B", "POST_BREAKDOWN_MANAGEMENT", "CADCHF", "inverse lower-range pause not reversal", "TRAIL_OR_WAIT", "TRAIL_SHORT_OR_WAIT"),
    GoldenPattern("EARLY_INVERSE_OPEN_LANE_CONFIRMATION", "A", "INVERSE_THEME_CONFIRMATION", "CADJPY", "early CAD-base inverse confirmation", "OWN_TRIGGER_REQUIRED"),
    GoldenPattern("DELAYED_INVERSE_IGNITION", "A", "DELAYED_INVERSE_CONFIRMATION", "CADJPY", "weak inverse signal before H4 breakdown", "WAIT_SELL_CONFIRMATION"),
    GoldenPattern("INVERSE_MIRROR_BREAKDOWN_CONFIRMATION", "S", "MIRROR_BASKET_CONFIRMATION", "CADJPY/CADCHF", "inverse breakdown sell candidate if trigger exists", "SELL_RETEST_OR_OWN_TRIGGER"),
    GoldenPattern("LOWER_RANGE_NO_CHASE_FILTER", "S", "EXHAUSTION_FILTER", "CADJPY", "avoid late sell after lower-range extension", "NO_MARKET_CHASE", "WAIT_PULLBACK_OR_BREAKDOWN_RETEST"),
    GoldenPattern("INVERSE_LATE_SELL_TRAP", "S", "TRAP_FILTER", "CADJPY", "late sell trap after breakdown", "NO_TRADE", block_reason="LATE_SELL_TRAP"),
    GoldenPattern("CLEAN_BLOCK_BUT_THEME_CONFLICT", "S", "THEME_CONFLICT_FILTER", "CADJPY", "clean pressure blocked by H4/D1/theme conflict", "NO_TRADE", block_reason="THEME_CONFLICT"),
    GoldenPattern("JPY_ALIGNMENT_REQUIRED", "S", "JPY_BASKET_FILTER", "CADJPY/USDJPY", "JPY-cross requires JPY basket validation", "REQUIRE_EXTRA_FILTER"),
    GoldenPattern("MICROBURST_FOLLOWTHROUGH_RECLAIM", "S-", "MICROBURST_FOLLOWTHROUGH", "GBPJPY/AUDJPY", "compact high-density microburst can reinforce continuation only after reclaim or pullback hold", "BUY_RECLAIM_OR_PULLBACK_HOLD", "NO_MARKET_CHASE_CONFIRM_THEME", golden_references=("GBPJPY", "AUDJPY"), pair_specific_calibration=("JPY_CROSS_CHECK_JPY_BASKET", "CHF_CROSS_CHECK_CHF_THEME", "METAL_CHECK_SESSION_VOLATILITY_SPREAD")),
    GoldenPattern("CLEAN_5M_TIMING_GATE_NOT_FINAL", "A", "TIMING_GATE", "GBPJPY", "clean five-minute timing block is watch-only until phase/context confirms", "ENTRY_WATCH_ONLY_WAIT_RECLAIM", "WAIT_M15_H1_RECLAIM", golden_references=("GBPJPY",)),
    GoldenPattern("HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "A-", "CONTEXT_FILTER", "GBPJPY/AUDJPY/EURCHF", "high density near exhaustion, bearish context, or upper range blocks blind chase", "NO_CHASE_PROTECT_OR_WAIT_RETEST", "PROTECT_OR_WAIT_RETEST", block_reason="HIGH_DENSITY_CONTEXT_NO_CHASE", golden_references=("GBPJPY", "AUDJPY", "EURCHF")),
    GoldenPattern("LIQUIDATION_RECLAIM_REQUIRED", "S", "LIQUIDATION_RECLAIM", "EURJPY", "extreme liquidation candle requires reclaim or breakdown confirmation before execution", "WATCH_ONLY_UNTIL_RECLAIM", "WAIT_RECLAIM_OR_BREAKDOWN_CONFIRMATION", block_reason="LIQUIDATION_RECLAIM_REQUIRED", golden_references=("EURJPY",), pair_specific_calibration=("JPY_CROSS_CHECK_JPY_BASKET", "CHF_CROSS_CHECK_CHF_THEME", "CAD_CROSS_CHECK_CAD_THEME", "METAL_CHECK_SESSION_VOLATILITY_SPREAD")),
    GoldenPattern("THEME_CONTEXT_ONLY_NOT_STANDALONE", "S", "THEME_CONTEXT", "EURJPY", "theme or basket dominance boosts selection but is not standalone execution proof", "PAIR_SELECTION_BOOST_ONLY", "WAIT_PRICE_CONTEXT", block_reason="THEME_CONTEXT_ONLY", golden_references=("EURJPY",), pair_specific_calibration=("JPY_BASKET_FOR_JPY_PAIRS", "CHF_BASKET_FOR_CHF_PAIRS", "CAD_BASKET_FOR_CAD_PAIRS", "LOCAL_VOLATILITY_AND_SPREAD")),
    GoldenPattern("MID_RANGE_CONTINUATION_PULLBACK_REQUIRED", "A", "CONTINUATION_PULLBACK_REQUIRED", "EURJPY", "strong structure close near an extreme needs pullback or reclaim because chase RR is poor", "PULLBACK_OR_RECLAIM_ONLY", "NO_CHASE", block_reason="MID_RANGE_PULLBACK_REQUIRED", golden_references=("EURJPY",), pair_specific_calibration=("ATR_BASED_PULLBACK_DISTANCE", "RECENT_HIGH_LOW_DISTANCE", "SESSION_VOLATILITY", "THEME_BASKET_CONFIRMATION")),
    GoldenPattern("PHASE_SENSITIVE_BREAKDOWN", "S", "BREAKDOWN_CONTINUATION", "USDJPY", "breakdown cascade/liquidation sell", "SELL_RETEST_ONLY", "NO_MARKET_CHASE"),
    GoldenPattern("UPPER_ABSORPTION_WARNING", "S", "EXHAUSTION_MANAGEMENT", "USDJPY", "pressure at resistance is protect/sell watch", "NO_NEW_BUY", "PROTECT_LONG_OR_SELL_WATCH"),
    GoldenPattern("LIQUIDATION_EXPANSION", "S", "VOLATILITY_EXPANSION", "USDJPY", "large expansion candle continuation via retest", "RETEST_ONLY", "SELL_AFTER_PULLBACK_NO_MARKET_CHASE"),
    GoldenPattern("SPARSE_ARCHIVE", "B", "ARCHIVE_FILTER", "USDJPY", "long duration with tiny event count", "NO_TRADE", block_reason="SPARSE_PRESSURE"),
    GoldenPattern("BEARISH_OR_BULLISH_CONTINUATION_AFTER_HOT_BLOCK", "S", "PHASE_SENSITIVE_CONTINUATION", "NZDCHF", "hot block follows current intraday phase and must not be forced into opposite raw direction", "PHASE_CONTINUATION_RETEST_OR_PROTECT", "FOLLOW_PHASE_RETEST_OR_PROTECT", golden_references=("NZDCHF",)),
    GoldenPattern("COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", "A-", "COUNTER_RECLAIM_WATCH", "NZDCHF/EURCHF", "counter microburst after sell-off or failed first hour is reclaim watch, not final reversal", "RECLAIM_WATCH_OR_PARTIAL_EXIT", "WAIT_RECLAIM_CONFIRMATION", golden_references=("NZDCHF", "EURCHF")),
    GoldenPattern("REPEATED_PRESSURE_MANAGEMENT_ALERT", "B+", "MANAGEMENT_ALERT", "NZDCHF", "repeated pressure in conflicting phase is management alert, not execution-grade", "WAIT_BREAK_OR_RECLAIM", "MANAGEMENT_ALERT", golden_references=("NZDCHF",)),
    GoldenPattern("DELAYED_FOLLOWTHROUGH_WATCH", "A-", "DELAYED_FOLLOWTHROUGH", "EURCHF", "theme pressure can recover later but is not instant execution proof", "DELAYED_WATCH", "WAIT_SUPPORT_HOLD_OR_RECLAIM", golden_references=("EURCHF",)),
    GoldenPattern("MULTI_WAVE_PRIORITY", "A", "MULTI_WAVE", "EURAUD", "burst to continuation to sustained pressure", "WATCH_HIGH"),
    GoldenPattern("SAME_PAIR_TAKEOVER", "A", "TAKEOVER", "GBPNZD", "pair takeover without intervention", "WATCH_HIGH"),
    GoldenPattern("SAME_PAIR_TAKEOVER_GRIND", "S", "TAKEOVER", "GBPNZD", "long medium-density follow-through", "RETEST_ONLY"),
    GoldenPattern("TAKEOVER_TO_LATE_REVERSAL", "S", "TAKEOVER_EXPIRY", "GBPNZD", "valid takeover expired by H4/D1 reversal", "EXPIRE_OR_PROTECT"),
    GoldenPattern("CHOPPY_TAKEOVER_CONTINUATION", "A", "TAKEOVER", "GBPNZD", "follow-through with whipsaw risk", "REDUCED_RISK_RETEST_ONLY"),
    GoldenPattern("DAILY_CONFLICT_AFTER_INTRADAY_TAKEOVER", "S", "DAILY_CONFLICT_FILTER", "GBPNZD", "daily close against intraday direction", "NO_NEW_ENTRY", block_reason="DAILY_CONFLICT"),
    GoldenPattern("MAJOR_PAIR_DELAYED_CONTINUATION", "A", "MAJOR_PAIR_CONTEXT", "EURUSD", "major pair delayed follow-through", "WAIT_RECLAIM"),
    GoldenPattern("PULLBACK_WITHIN_H4_EXPANSION", "A", "CONTINUATION_FILTER", "EURUSD", "M15 pullback inside H4 expansion", "WAIT_PULLBACK_END"),
    GoldenPattern("SIGNALWATCH_LIFECYCLE_FINALIZER", "S", "SIGNAL_LIFECYCLE", "USDCAD", "watch must finalize or expire", "FINALIZER_REQUIRED"),
    GoldenPattern("ABSORPTION_WATCH_FAILED", "S", "SIGNALWATCH_LIFECYCLE", "USDCAD", "sell watch failed at resistance", "NO_SELL", "WAIT_RECLAIM_OR_BREAKDOWN"),
    GoldenPattern("HIGH_DENSITY_ABSORPTION_WITH_RECLAIM", "S", "ABSORPTION_REVERSAL", "USDCAD", "high-density resistance absorption reclaimed", "RETEST_ONLY", "BLOCK_SELL_WAIT_BUY_RETEST"),
    GoldenPattern("SLOW_ACTIVE_SIGNAL_SEED", "A", "SIGNAL_LIFECYCLE", "USDCAD", "slow but valid active seed", "RETEST_ONLY"),
    GoldenPattern("METAL_SUSTAINED_PRESSURE_CONTEXT", "S", "METAL_PRESSURE", "XAUUSD", "metal pressure requires special hold policy", "RETEST_OR_SCALP_ONLY", "FAST_PROTECT", "SHORT_WINDOW_UNLESS_H4_CONFIRMS"),
    GoldenPattern("METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", "S", "METAL_LIFECYCLE", "XAUUSD", "fast MFE then whipsaw", "SCALP_OR_SHORT_INTRADAY", "MOVE_BE_OR_PARTIAL_AFTER_FAST_MFE", "SHORT_INTRADAY"),
    GoldenPattern("METAL_EXTENDED_MFE_THEN_REVERSAL", "S", "METAL_REVERSAL_RISK", "XAUUSD", "large MFE then larger reversal", "INTRADAY_ONLY", "PARTIAL_TP_AND_TRAIL", "INTRADAY_ONLY"),
    GoldenPattern("METAL_NO_CHASE_AFTER_UPPER_SPIKE", "S", "METAL_RISK_FILTER", "XAUUSD", "no buy chase after upper spike", "NO_MARKET_CHASE", "WAIT_PULLBACK_OR_RECLAIM", "SHORT_INTRADAY"),
)


PAIR_ROLE_MAP: dict[str, dict[str, Any]] = {
    "GBPCAD": {"default_role": "PRIMARY_TIMING_CAD_WEAKNESS", "golden_patterns": ["OPEN_LANE_TIMING_VALID", "ZERO_DRAWDOWN_FOLLOWTHROUGH", "PRE_IGNITION_COUNTERFLOW_TRAP", "HIGH_DENSITY_ACCELERATION", "LATE_DENSE_CONGESTION", "LATE_MICROBOOST_DECISION_POINT"]},
    "EURCAD": {"default_role": "DELAYED_IGNITION_CAD_WEAKNESS", "golden_patterns": ["DELAYED_IGNITION_MICROBOOST", "LATE_UPPER_MICROBOOST"]},
    "AUDCAD": {"default_role": "LATE_SATURATION_CAD_WEAKNESS", "golden_patterns": ["LATE_UPPER_MICROBOOST", "SATURATION_MICROBOOST_WARNING"]},
    "NZDCAD": {"default_role": "SECONDARY_CONFIRMATION_CAD_WEAKNESS", "golden_patterns": ["SECONDARY_OPEN_LANE_CONFIRMATION", "LATE_SECONDARY_SATURATION", "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY"]},
    "CADCHF": {"default_role": "CLEAN_INVERSE_CONFIRMATION_CAD_WEAKNESS", "golden_patterns": ["INVERSE_MIRROR_BREAKDOWN", "INVERSE_COOLING_PAUSE", "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY"]},
    "CADJPY": {"default_role": "JPY_SENSITIVE_INVERSE_CONFIRMATION", "golden_patterns": ["EARLY_INVERSE_OPEN_LANE_CONFIRMATION", "DELAYED_INVERSE_IGNITION", "INVERSE_MIRROR_BREAKDOWN_CONFIRMATION", "LOWER_RANGE_NO_CHASE_FILTER", "INVERSE_LATE_SELL_TRAP", "CLEAN_BLOCK_BUT_THEME_CONFLICT", "JPY_ALIGNMENT_REQUIRED"]},
    "EURJPY": {"default_role": "JPY_BASKET_GOLDEN_REFERENCE", "golden_patterns": ["LIQUIDATION_RECLAIM_REQUIRED", "THEME_CONTEXT_ONLY_NOT_STANDALONE", "MID_RANGE_CONTINUATION_PULLBACK_REQUIRED", "JPY_ALIGNMENT_REQUIRED"]},
    "USDJPY": {"default_role": "PHASE_SENSITIVE_JPY_MAJOR", "golden_patterns": ["PHASE_SENSITIVE_BREAKDOWN", "UPPER_ABSORPTION_WARNING", "LIQUIDATION_EXPANSION", "SPARSE_ARCHIVE", "LOWER_RANGE_NO_CHASE_FILTER", "JPY_ALIGNMENT_REQUIRED"]},
    "GBPJPY": {"default_role": "PHASE_SENSITIVE_JPY_CROSS", "golden_patterns": ["MICROBURST_FOLLOWTHROUGH_RECLAIM", "CLEAN_5M_TIMING_GATE_NOT_FINAL", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "JPY_ALIGNMENT_REQUIRED"]},
    "AUDJPY": {"default_role": "JPY_WEAKNESS_CONFIRMATION_CROSS", "golden_patterns": ["OPEN_LANE_TIMING_VALID", "MICROBURST_FOLLOWTHROUGH_RECLAIM", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "JPY_ALIGNMENT_REQUIRED"]},
    "NZDCHF": {"default_role": "CHF_CROSS_PHASE_SENSITIVE", "golden_patterns": ["BEARISH_OR_BULLISH_CONTINUATION_AFTER_HOT_BLOCK", "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", "REPEATED_PRESSURE_MANAGEMENT_ALERT"]},
    "EURCHF": {"default_role": "CHF_WEAKNESS_MICROBOOST_CROSS", "golden_patterns": ["COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", "DELAYED_FOLLOWTHROUGH_WATCH", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE"]},
    "EURUSD": {"default_role": "MAJOR_CONTEXT_PAIR", "golden_patterns": ["MAJOR_PAIR_DELAYED_CONTINUATION", "PULLBACK_WITHIN_H4_EXPANSION"]},
    "GBPNZD": {"default_role": "TAKEOVER_CONTEXTUAL_CROSS", "golden_patterns": ["SAME_PAIR_TAKEOVER", "SAME_PAIR_TAKEOVER_GRIND", "TAKEOVER_TO_LATE_REVERSAL", "CHOPPY_TAKEOVER_CONTINUATION", "DAILY_CONFLICT_AFTER_INTRADAY_TAKEOVER"]},
    "USDCAD": {"default_role": "MACRO_ANCHOR_AND_SIGNALWATCH_LIFECYCLE", "golden_patterns": ["SLOW_ACTIVE_SIGNAL_SEED", "SIGNALWATCH_LIFECYCLE_FINALIZER", "ABSORPTION_WATCH_FAILED", "HIGH_DENSITY_ABSORPTION_WITH_RECLAIM"]},
    "XAUUSD": {"default_role": "METAL_VOLATILITY_LIFECYCLE", "golden_patterns": ["METAL_SUSTAINED_PRESSURE_CONTEXT", "METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", "METAL_EXTENDED_MFE_THEN_REVERSAL", "METAL_NO_CHASE_AFTER_UPPER_SPIKE"]},
    "XAGUSD": {"default_role": "METAL_VOLATILITY_LIFECYCLE", "golden_patterns": ["METAL_SUSTAINED_PRESSURE_CONTEXT", "METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", "METAL_EXTENDED_MFE_THEN_REVERSAL", "METAL_NO_CHASE_AFTER_UPPER_SPIKE"]},
    "EURAUD": {"default_role": "MULTI_WAVE_PRIORITY_PAIR", "golden_patterns": ["MULTI_WAVE_PRIORITY"]},
}

_PATTERN_BY_ID = {pattern.pattern_id: pattern for pattern in GOLDEN_PATTERNS}


def get_pattern(pattern_id: str | None) -> GoldenPattern | None:
    return _PATTERN_BY_ID.get(str(pattern_id or "").upper())


def pair_role_for_symbol(symbol: str | None) -> dict[str, Any]:
    normalized = str(symbol or "").upper()
    if normalized in PAIR_ROLE_MAP:
        return PAIR_ROLE_MAP[normalized]
    if normalized.startswith(("XAU", "XAG")):
        return PAIR_ROLE_MAP["XAUUSD"]
    return {"default_role": "GENERAL_SIGNALTHROTTLE_PAIR", "golden_patterns": []}
