"""Static Golden Pattern Database v1 for SignalThrottle analysis.

The registry is deliberately analysis-only.  It describes known market-pattern
archetypes and pair roles, but it never executes trades and never bypasses L12.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - production fallback when PyYAML is absent.
    yaml = None


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


_STATIC_GOLDEN_PATTERNS: tuple[GoldenPattern, ...] = (
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
    GoldenPattern("CLEAN_BLOCK_BUT_THEME_CONFLICT", "S", "THEME_CALIBRATION_CONTEXT", "CADJPY", "legacy theme conflict reference; price/structure/lifecycle must decide execution", "WATCH_PRICE_STRUCTURE"),
    GoldenPattern("JPY_ALIGNMENT_REQUIRED", "S", "JPY_BASKET_FILTER", "CADJPY/USDJPY", "JPY-cross records JPY basket calibration metadata", "CALIBRATION_METADATA"),
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
    GoldenPattern("METAL_PRESSURE_BROAD_FOLLOWTHROUGH_BUT_BLOCK_WHIPSAW", "A", "METAL_VOLATILITY_MANAGEMENT", "XAGUSD", "XAGUSD validates that broad metal pressure can follow through while the individual intraday block whipsaws, so execution requires reclaim or rejection confirmation", "RECLAIM_OR_REJECTION_CONFIRMATION", "FAST_PROTECT_OR_PARTIAL_AFTER_MFE", "SHORT_INTRADAY_UNLESS_H4_CONFIRMS", block_reason="METAL_BLOCK_WHIPSAW_RISK", scope="UNIVERSAL_WITH_ASSET_CLASS_CALIBRATION", applies_to="ALL_METALS_IF_CONDITIONS_MATCH", golden_references=("XAGUSD",), pair_specific_calibration=("METAL_PRESSURE_BLOCK_NOT_AUTO_DIRECTION", "BROAD_BIAS_CAN_BE_VALID_WHILE_INTRADAY_BLOCK_WHIPSAWS", "FAST_PROTECT_AND_RECLAIM_FILTER_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM", "A-", "NO_CHASE_FILTER", "XAGUSD", "silver recovery below key EMA zone is no-chase until reclaim and hold, or rejection plus support breakdown confirms the opposite side", "NO_MARKET_CHASE", "WAIT_RECLAIM_75_35_75_50_OR_REJECTION_BREAKDOWN_74_27", "WAIT_RECLAIM_OR_REJECTION", block_reason="XAGUSD_REPAIR_BELOW_EMA_NO_CHASE", scope="UNIVERSAL_WITH_METAL_CALIBRATION", applies_to="ALL_METALS_IF_CONDITIONS_MATCH", golden_references=("XAGUSD",), pair_specific_calibration=("D1_ABOVE_EMA200_BELOW_EMA50", "H4_H1_BELOW_EMA50", "M15_RECOVERY_BELOW_KEY_EMA", "STRUCTURE_TARGET_REQUIRED", "NOT_PAIR_LOCKED")),
    # --- Universal Pattern Family v2 (migrated from pair-specific golden logic) ---
    GoldenPattern("LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", "S", "CONTINUATION_TIMING", "GBPCAD", "low density sustained pressure block signals open lane continuation before expansion when own price phase confirms", "ENTRY_WATCH_OR_BUY_WATCH", golden_references=("GBPCAD",)),
    GoldenPattern("ALLOWED_CANARY_QUORUM", "A", "CANARY_CONFIDENCE", "AUDCAD/GBPCAD", "engine repeated permission burst is confidence signal not final direction", "WATCH_BOOST_ONLY", golden_references=("AUDCAD", "GBPCAD", "USDJPY", "GBPJPY")),
    GoldenPattern("FALSE_COUNTERFLOW_CANARY", "S", "DIRECTION_VALIDATION", "GBPCAD", "allowed direction opposite to confirmed price phase is false canary to be blocked", "BLOCK_RAW_DIRECTION_WAIT", block_reason="FALSE_COUNTERFLOW_CANARY", golden_references=("GBPCAD",)),
    GoldenPattern("HIGH_DENSITY_ACCELERATION_CONTINUATION", "A", "CONTINUATION_MANAGEMENT", "GBPCAD/GBPJPY", "high density block with price followthrough confirms continuation when structure has room", "REINFORCE_OR_RETEST_ONLY", "HOLD_OR_TRAIL", golden_references=("GBPCAD", "GBPJPY", "EURCAD", "CADJPY")),
    GoldenPattern("LATE_DENSE_PRESSURE_MANAGEMENT_ALERT", "S", "TRADE_MANAGEMENT", "GBPCAD/EURCAD", "short high-density burst near key level after move is protect-no-chase management alert", "NO_NEW_ENTRY", "PROTECT_PROFIT_OR_PARTIAL_CLOSE", golden_references=("GBPCAD", "EURCAD", "USDJPY")),
    GoldenPattern("CLEAN_SAME_PAIR_TAKEOVER", "A", "PAIR_PRIORITY_SELECTION", "EURAUD/GBPNZD", "same pair dominates run sequence without interruption and with phase alignment", "PRIORITY_SIGNAL_WATCH", golden_references=("EURAUD", "GBPNZD")),
    GoldenPattern("BASKET_THEME_CONFIRMATION_CONTEXT", "A", "OPTIONAL_CONTEXT", "NZDCAD/CADJPY/CADCHF", "multiple related pairs active with consistent basket direction boosts pair selection score only", "BOOST_SCORE_ONLY", golden_references=("NZDCAD", "CADJPY", "CADCHF")),
    GoldenPattern("JPY_BASKET_THEME_FOLLOWTHROUGH", "A", "BASKET_THEME_CONFIRMATION", "CHFJPY", "JPY basket member with OHLC follow-through validates theme pressure but still requires own price-phase trigger", "VALIDATED_THEME_FOLLOWTHROUGH", "WATCH_PRICE_PHASE_AND_OWN_TRIGGER", block_reason="THEME_FOLLOWTHROUGH_REQUIRES_OWN_TRIGGER", golden_references=("CHFJPY",), pair_specific_calibration=("JPY_BASKET_MEMBER_REFERENCE", "MFE_MAE_VALIDATION_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("FRAGMENTED_BASKET_ROTATION_NOT_ENTRY", "S", "BASKET_ROTATION_FILTER", "CHFJPY", "large fragmented basket rotation is watchlist-only until a clean same-pair block or reclaim appears", "WATCHLIST_ONLY", "NO_FINAL_SIGNAL_UNTIL_CLEAN_BLOCK_OR_RECLAIM", block_reason="FRAGMENTED_ROTATION_NOT_ENTRY", golden_references=("CHFJPY",), pair_specific_calibration=("BROAD_ROTATION_FRAGMENTED", "SAME_PAIR_BLOCK_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("MTF_BULLISH_PULLBACK_DECISION", "A", "PRICE_PHASE_DECISION", "CHFJPY", "D1/H4 bullish trend with H1/M15 pullback is a decision state, not a market chase", "BUY_RECLAIM_OR_SUPPORT_HOLD", "WAIT_SUPPORT_HOLD_OR_H1_BREAKDOWN", block_reason="PULLBACK_DECISION_NEEDS_RECLAIM_OR_BREAKDOWN", golden_references=("CHFJPY",), pair_specific_calibration=("D1_H4_TREND_H1_M15_PULLBACK", "SUPPORT_RECLAIM_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("LATE_SESSION_EXPANSION_FAIL", "A", "SESSION_CLOSE_MANAGEMENT", "CHFJPY", "late-session failed expansion is management context and should not create a fresh entry", "NO_NEW_ENTRY", "PROTECT_OR_REVALIDATE_NEXT_SESSION", block_reason="LATE_SESSION_EXPANSION_FAIL", golden_references=("CHFJPY",), pair_specific_calibration=("SESSION_CLOSE_REVALIDATION", "NOT_PAIR_LOCKED")),
    GoldenPattern("JPY_BASKET_SECONDARY_CONFIRMATION", "A", "BASKET_CONFIRMATION", "NZDJPY", "JPY basket member confirms theme pressure as Tier A reference but is not a primary clean timing leader", "BOOST_SCORE_ONLY", "WATCH_OWN_PRICE_PHASE_AND_RECLAIM", block_reason="JPY_SECONDARY_REQUIRES_OWN_TRIGGER", golden_references=("NZDJPY",), pair_specific_calibration=("JPY_BASKET_SECONDARY_MEMBER", "MODERATE_OWN_EVENT_COUNT", "POST_WINDOW_MFE_MAE_VALIDATED", "NOT_PAIR_LOCKED"), applies_to="ALL_JPY_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("FRAGMENTED_THEME_FOLLOWTHROUGH", "A", "DELAYED_THEME_FOLLOWTHROUGH", "NZDJPY", "fragmented basket member can follow through after the window but must stay watch-only until reclaim", "DELAYED_WATCH", "WAIT_RECLAIM_OR_SUPPORT_HOLD", block_reason="FRAGMENTED_THEME_REQUIRES_RECLAIM", golden_references=("NZDJPY",), pair_specific_calibration=("FRAGMENTED_BASKET_MEMBER", "DELAYED_MFE_AFTER_WINDOW", "NOT_PAIR_LOCKED")),
    GoldenPattern("DELAYED_JPY_CROSS_CONTINUATION", "A", "DELAYED_CONTINUATION", "NZDJPY", "JPY cross pressure can become continuation only after delayed reclaim or recovery confirms", "DELAYED_WATCH", "WAIT_RECLAIM_OR_STRUCTURE_TARGET", block_reason="DELAYED_CONTINUATION_REQUIRES_RECLAIM", golden_references=("NZDJPY",), pair_specific_calibration=("IMMEDIATE_FOLLOWTHROUGH_WEAK_OR_NEGATIVE", "LATER_RECLAIM_VALIDATED", "MFE_MAE_VALIDATION_REQUIRED", "NOT_PAIR_LOCKED"), applies_to="ALL_JPY_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("MACRO_BULLISH_INTRADAY_PULLBACK_DECISION", "A", "MULTITIMEFRAME_DECISION", "NZDJPY", "macro bullish pair with intraday pullback is a decision state requiring reclaim or support hold", "BUY_RECLAIM_OR_SUPPORT_HOLD", "WAIT_SUPPORT_HOLD_OR_H1_BREAKDOWN", block_reason="MACRO_PULLBACK_NEEDS_RECLAIM_OR_SUPPORT_HOLD", golden_references=("NZDJPY",), pair_specific_calibration=("D1_H4_BULLISH_BIAS", "H1_M15_PULLBACK_STATE", "NO_BUY_CHASE", "NOT_PAIR_LOCKED")),
    GoldenPattern("POST_EXPANSION_NO_CHASE_FILTER", "S", "RISK_MANAGEMENT", "NZDJPY", "post-expansion pullback from upper range blocks fresh chase until reclaim and retest", "NO_MARKET_CHASE", "PROTECT_OR_WAIT_RETEST", block_reason="POST_EXPANSION_NO_CHASE", golden_references=("NZDJPY",), pair_specific_calibration=("PRIOR_EXPANSION_UPPER_RANGE_PULLBACK", "INTRADAY_REPAIR_NOT_COMPLETE", "NOT_PAIR_LOCKED")),
    GoldenPattern("LOW_DENSITY_MAJOR_PAIR_CONTINUATION", "A", "CONTINUATION_TIMING", "GBPUSD", "low-density major pair continuation can be valid when phase, structure target, and RR confirm", "ENTRY_WATCH_OR_DIRECT_IF_STRUCTURE_READY", "WAIT_STRUCTURE_TARGET_AND_RR", block_reason="STRUCTURE_PHASE_REQUIRED", golden_references=("GBPUSD",), pair_specific_calibration=("MAJOR_PAIR_LOW_DENSITY_BLOCK", "SMALL_BLOCK_DELTA", "POST_WINDOW_MFE_MAE_VALIDATED", "NOT_PAIR_LOCKED"), applies_to="ALL_MAJOR_OR_HIGH_LIQUIDITY_PAIRS_IF_CONDITIONS_MATCH"),
    GoldenPattern("BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY", "S", "PAIR_SELECTION_SAFETY", "GBPUSD", "high event count in broad rotation is a watchlist/theme alert until clean pair phase confirms", "WATCHLIST_ONLY", "FETCH_M15_H1_PRICE_PHASE", block_reason="BROAD_ROTATION_NOT_SINGLE_PAIR_ENTRY", golden_references=("GBPUSD",), pair_specific_calibration=("HIGH_EVENT_COUNT_NOT_AUTO_ENTRY", "NET_DELTA_SMALL_RANGE_LARGE", "THEME_ALERT_ONLY", "NOT_PAIR_LOCKED")),
    GoldenPattern("DELAYED_GBP_CONTINUATION_AFTER_WAIT", "A", "DELAYED_CONTINUATION", "GBPUSD", "WAIT-stage major/GBP pressure can become continuation only after reclaim or support hold", "DELAYED_WATCH", "WAIT_RECLAIM_OR_SUPPORT_HOLD", block_reason="DELAYED_GBP_CONTINUATION_REQUIRES_RECLAIM", golden_references=("GBPUSD",), pair_specific_calibration=("SIGNALTHROTTLE_INTEL_WAIT_VALIDATED", "NEGATIVE_OR_FLAT_WINDOW_DELTA", "LATER_RECLAIM_MFE_MAE_VALIDATED", "NOT_PAIR_LOCKED"), applies_to="ALL_GBP_OR_MAJOR_PAIRS_IF_CONDITIONS_MATCH"),
    GoldenPattern("MAJOR_PAIR_POST_EXPANSION_NO_CHASE", "S", "RISK_MANAGEMENT", "GBPUSD", "major pair late continuation after D1 expansion is hold/trail context, not fresh market chase", "NO_MARKET_CHASE", "HOLD_TRAIL_OR_WAIT_PULLBACK", block_reason="MAJOR_PAIR_POST_EXPANSION_NO_CHASE", golden_references=("GBPUSD",), pair_specific_calibration=("PRIOR_D1_EXPANSION", "LATE_CONTINUATION_BLOCK", "NEXT_DAY_REJECTION_OR_COOLING_RISK", "NOT_PAIR_LOCKED"), applies_to="ALL_MAJOR_OR_HIGH_LIQUIDITY_PAIRS_IF_CONDITIONS_MATCH"),
    GoldenPattern("LOW_DENSITY_BLOCK_FALSE_CONTINUATION", "A", "PRESSURE_BLOCK_VALIDATION", "AUDNZD", "low-density cross pressure block can be a false-continuation reference and must not become auto-entry without own phase confirmation", "WATCH_ONLY_UNTIL_OWN_PHASE_CONFIRMS", "WAIT_RECLAIM_OR_FADE_CONFIRMATION", block_reason="LOW_DENSITY_BLOCK_FALSE_CONTINUATION_RISK", golden_references=("AUDNZD",), pair_specific_calibration=("LOW_DENSITY_PRESSURE_BLOCK", "WEAK_BUY_FOLLOWTHROUGH", "POST_WINDOW_FADE_VALIDATED", "NOT_PAIR_LOCKED")),
    GoldenPattern("AUDNZD_RELATIVE_STRENGTH_DECISION_PAIR", "A", "CROSS_RELATIVE_STRENGTH", "AUDNZD", "AUDNZD pressure is a relative-strength decision reference; do not copy AUD or NZD theme direction into execution without own trigger", "WAIT_AUD_NZD_DECISION_CONFIRMATION", "CHECK_OWN_PRICE_PHASE_AND_STRUCTURE", block_reason="RELATIVE_STRENGTH_DECISION_NOT_AUTO_ENTRY", golden_references=("AUDNZD",), pair_specific_calibration=("AUD_NZD_RELATIVE_STRENGTH_DECISION", "SUPPORTING_CROSS_CONTEXT", "NOT_PAIR_LOCKED"), applies_to="ALL_AUD_NZD_OR_SUPPORTING_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("SUPPORTING_CROSS_NOT_PRIMARY_LEADER", "S", "PAIR_SELECTION_SAFETY", "AUDNZD/EURNZD", "supporting cross activity validates theme context but must not inherit the leader pair signal without its own clean phase and trigger", "WATCHLIST_OR_SCORE_CONTEXT_ONLY", "REQUIRE_OWN_TRIGGER_AND_PRICE_PHASE", block_reason="SUPPORTING_CROSS_NOT_PRIMARY_LEADER", golden_references=("AUDNZD", "EURNZD"), pair_specific_calibration=("LEADER_PAIR_SEPARATION_REQUIRED", "SUPPORTING_EVENT_COUNT_NOT_AUTO_ENTRY", "NOT_PAIR_LOCKED"), applies_to="ALL_SUPPORTING_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("BULLISH_REPAIR_UPPER_DECISION_NO_CHASE", "A", "MTF_REPAIR_MANAGEMENT", "AUDNZD", "bullish repair near upper decision zone is no-chase until pullback, retest, reclaim, and structure target validate", "PULLBACK_RETEST_RECLAIM_ONLY", "WAIT_PULLBACK_HOLD_OR_RECLAIM", block_reason="BULLISH_REPAIR_UPPER_DECISION_NO_CHASE", golden_references=("AUDNZD",), pair_specific_calibration=("BULLISH_REPAIR_AT_UPPER_DECISION_ZONE", "BUY_CHASE_BLOCKED", "STRUCTURE_TARGET_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH", "A", "BASKET_CONFIRMATION", "AUDCHF", "AUDCHF validates CHF-weakness confirmation with clean but moderate BUY follow-through; use as secondary confirmation, not primary leader", "BUY_RETEST_OR_CONFIRMATION", "USE_AS_CHF_WEAKNESS_CONFIRMATION", block_reason="SUPPORTING_CONFIRMATION_REQUIRES_OWN_TRIGGER", applies_to="ALL_CHF_CROSSES_IF_CONDITIONS_MATCH", golden_references=("AUDCHF",), pair_specific_calibration=("CHF_WEAKNESS_CONTEXT", "SUPPORTING_CONFIRMATION_PAIR", "SMALL_MAE_POSITIVE_MODERATE_MFE", "SECONDARY_SIZE_THAN_PRIMARY_CHF_PAIR", "NOT_PAIR_LOCKED")),
    GoldenPattern("SUPPORTING_EUR_CROSS_NOT_LEADER", "A", "PAIR_SELECTION_SAFETY", "EURNZD/EURGBP", "supporting EUR-cross pressure is reference context only; EUR theme activity must not be copied into EURGBP or EURNZD without own reclaim, breakdown, or price-phase proof", "WAIT_OWN_PRICE_PHASE_CONFIRMATION", "VALIDATE_OWN_EUR_CROSS_PRICE_PHASE", block_reason="SUPPORTING_EUR_CROSS_NOT_LEADER", golden_references=("EURNZD", "EURGBP"), pair_specific_calibration=("SUPPORTING_EUR_CROSS_RADAR", "EURAUD_LEADER_DIVERGENCE", "EURGBP_GBP_STRENGTH_VS_EUR_FILTER", "NOT_PAIR_LOCKED"), applies_to="ALL_EUR_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("EURGBP_RANGE_COMPRESSION_FILTER", "B+", "LOW_MOMENTUM_FILTER", "EURGBP", "EURGBP low-range compression and weak follow-through should filter out mid-range entries until clean reclaim or breakdown appears", "CLEAN_BREAK_OR_RECLAIM_REQUIRED", "WAIT_RECLAIM_ABOVE_RESISTANCE_OR_BREAKDOWN_BELOW_SUPPORT", block_reason="EURGBP_RANGE_COMPRESSION_NO_ENTRY", golden_references=("EURGBP",), pair_specific_calibration=("LOW_ATR_RANGE_COMPRESSION", "SMALL_EVENT_COUNT", "MFE_MAE_NOT_DECISIVE", "EUR_THEME_NOT_AUTO_BUY", "NOT_PAIR_LOCKED"), applies_to="ALL_LOW_MOMENTUM_OR_EUR_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("EURNZD_UPPER_FADE_AFTER_EUR_CROSS_PRESSURE", "A", "FALSE_CONTINUATION_FADE", "EURNZD", "EURNZD supporting EUR-cross pressure can mark upper-fade risk when buy continuation fails after recovery into resistance", "FADE_WATCH_ONLY_UNTIL_REJECTION_CONFIRMS", "WAIT_REJECTION_OR_BREAKDOWN", block_reason="EUR_CROSS_UPPER_FADE_RISK", golden_references=("EURNZD",), pair_specific_calibration=("UPPER_REJECTION_AFTER_EUR_CROSS_PRESSURE", "BUY_FOLLOWTHROUGH_FAILED", "POST_WINDOW_SELL_MFE_VALIDATED", "NOT_PAIR_LOCKED"), applies_to="ALL_EUR_OR_NZD_CROSSES_IF_CONDITIONS_MATCH"),
    GoldenPattern("CROSS_THEME_LEADER_DIVERGENCE", "S", "PAIR_SELECTION_SAFETY", "EURNZD", "theme leader strength must not be copied to every same-base cross when supporting pairs diverge or sit near exhaustion", "LEADER_ONLY_UNLESS_SUPPORTING_PAIR_CONFIRMS", "SEPARATE_LEADER_FROM_SUPPORTING_CROSS", block_reason="CROSS_THEME_LEADER_DIVERGENCE", golden_references=("EURNZD",), pair_specific_calibration=("LEADER_CROSS_NOT_TRANSFERABLE", "SUPPORTING_PAIR_REQUIRES_OWN_PHASE", "NOT_PAIR_LOCKED"), applies_to="ALL_THEME_BASKETS_IF_CONDITIONS_MATCH"),
    GoldenPattern("MACRO_BEARISH_INTRADAY_REPAIR_DECISION", "A", "MULTITIMEFRAME_DECISION", "EURNZD", "macro bearish pair with intraday repair is a decision state; no buy chase until reclaim, and fade needs rejection or breakdown confirmation", "NO_BUY_CHASE_WAIT_REPAIR_CONFIRMATION", "WAIT_REJECTION_OR_RECLAIM", block_reason="MACRO_BEARISH_INTRADAY_REPAIR_DECISION", golden_references=("EURNZD",), pair_specific_calibration=("D1_H4_BEARISH_CONTEXT", "H1_M15_INTRADAY_REPAIR", "UPPER_RESISTANCE_DECISION_ZONE", "NOT_PAIR_LOCKED")),
    GoldenPattern("AUDCHF_BULLISH_ALIGNMENT_UPPER_NO_CHASE", "A", "NO_CHASE_FILTER", "AUDCHF", "AUDCHF bullish MTF alignment near recent high is valid CHF weakness context but fresh BUY entry waits for retest or breakout retest", "BUY_RETEST_OR_BREAKOUT_RETEST_ONLY", "WAIT_PULLBACK_0_56525_0_56490_OR_BREAKOUT_RETEST_0_56600", block_reason="AUDCHF_UPPER_ALIGNMENT_NO_CHASE", applies_to="ALL_CHF_CROSSES_IF_CONDITIONS_MATCH", golden_references=("AUDCHF",), pair_specific_calibration=("D1_H4_H1_ABOVE_EMA50", "PRICE_NEAR_RECENT_HIGH", "M1_MICRO_COOLING", "RETEST_OR_BREAKOUT_CONFIRMATION_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("AUDUSD_LOW_DRAWDOWN_BULLISH_FOLLOWTHROUGH", "A", "CONTINUATION_FOLLOWTHROUGH", "AUDUSD", "AUDUSD validates low-drawdown bullish follow-through after expansion, but entry still requires own pullback or reclaim rather than event-count auto-entry", "BUY_PULLBACK_OR_RECLAIM_ONLY", "WAIT_PULLBACK_HOLD_OR_RECLAIM_BEFORE_BUY", block_reason="AUDUSD_NO_BUY_CHASE_AT_UPPER_RANGE", applies_to="ALL_AUD_OR_MAJOR_PAIRS_IF_CONDITIONS_MATCH", golden_references=("AUDUSD",), pair_specific_calibration=("D1_BULLISH_EXPANSION", "LOW_DRAWDOWN_BUY_FOLLOWTHROUGH", "AUD_STRENGTH_USD_WEAKNESS_REFERENCE", "OWN_PRICE_PHASE_REQUIRED", "NOT_PAIR_LOCKED")),
    GoldenPattern("AUDUSD_POST_REJECTION_RECOVERY_FILTER", "A-", "RECOVERY_AFTER_REJECTION", "AUDUSD", "AUDUSD recovery after rejection can improve candidate quality, but one recovery candle is not enough for blind continuation without reclaim or pullback hold", "RECLAIM_OR_PULLBACK_HOLD_ONLY", "WAIT_RECLAIM_OR_NO_CHASE_AFTER_RECOVERY", block_reason="AUDUSD_POST_REJECTION_RECOVERY_NO_CHASE", applies_to="ALL_AUD_OR_MAJOR_PAIRS_IF_CONDITIONS_MATCH", golden_references=("AUDUSD",), pair_specific_calibration=("PRIOR_BEARISH_REJECTION", "BULLISH_RECOVERY_CANDLE", "RECLAIM_REQUIRED_AFTER_REJECTION", "STRONG_DAILY_CLOSE_DOES_NOT_BYPASS_EXECUTION_GATE", "NOT_PAIR_LOCKED")),
    GoldenPattern("TIMING_VALID_NOT_FINAL", "S", "SAFETY_GATE", "GBPJPY/EURCAD", "duration valid block but price phase unconfirmed means timing-only watch not final signal", "WAIT_PRICE_PHASE_CONFIRMATION", "WAIT_DIRECTION_VALIDATION", golden_references=("GBPJPY", "EURCAD", "CADJPY", "GBPCAD")),
    GoldenPattern("SIGNAL_LIFECYCLE_CONFLICT_WATCH", "S", "LIFECYCLE_MANAGEMENT", "USDJPY/USDCAD", "active signal exists and new opposing candidate requires lifecycle conflict resolution before action", "KEEP_ACTIVE_OR_WAIT_RESOLUTION", "WAIT_LIFECYCLE_RESOLUTION", block_reason="LIFECYCLE_CONFLICT_UNRESOLVED", golden_references=("USDJPY", "USDCAD")),
)


_STATIC_PAIR_ROLE_MAP: dict[str, dict[str, Any]] = {
    "GBPCAD": {"default_role": "PRIMARY_TIMING_CAD_WEAKNESS", "golden_patterns": ["OPEN_LANE_TIMING_VALID", "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", "ZERO_DRAWDOWN_FOLLOWTHROUGH", "PRE_IGNITION_COUNTERFLOW_TRAP", "FALSE_COUNTERFLOW_CANARY", "ALLOWED_CANARY_QUORUM", "HIGH_DENSITY_ACCELERATION", "HIGH_DENSITY_ACCELERATION_CONTINUATION", "LATE_DENSE_CONGESTION", "LATE_DENSE_PRESSURE_MANAGEMENT_ALERT", "LATE_MICROBOOST_DECISION_POINT"]},
    "EURCAD": {"default_role": "DELAYED_IGNITION_CAD_WEAKNESS", "golden_patterns": ["DELAYED_IGNITION_MICROBOOST", "LATE_UPPER_MICROBOOST"]},
    "AUDCAD": {"default_role": "LATE_SATURATION_CAD_WEAKNESS", "golden_patterns": ["LATE_UPPER_MICROBOOST", "SATURATION_MICROBOOST_WARNING"]},
    "NZDCAD": {"default_role": "SECONDARY_CONFIRMATION_CAD_WEAKNESS", "golden_patterns": ["SECONDARY_OPEN_LANE_CONFIRMATION", "LATE_SECONDARY_SATURATION", "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY"]},
    "CADCHF": {"default_role": "CLEAN_INVERSE_CONFIRMATION_CAD_WEAKNESS", "golden_patterns": ["INVERSE_MIRROR_BREAKDOWN", "INVERSE_COOLING_PAUSE", "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY"]},
    "CADJPY": {"default_role": "JPY_SENSITIVE_INVERSE_CONFIRMATION", "golden_patterns": ["EARLY_INVERSE_OPEN_LANE_CONFIRMATION", "DELAYED_INVERSE_IGNITION", "INVERSE_MIRROR_BREAKDOWN_CONFIRMATION", "LOWER_RANGE_NO_CHASE_FILTER", "INVERSE_LATE_SELL_TRAP", "CLEAN_BLOCK_BUT_THEME_CONFLICT", "JPY_ALIGNMENT_REQUIRED"]},
    "EURJPY": {"default_role": "JPY_BASKET_GOLDEN_REFERENCE", "golden_patterns": ["LIQUIDATION_RECLAIM_REQUIRED", "THEME_CONTEXT_ONLY_NOT_STANDALONE", "MID_RANGE_CONTINUATION_PULLBACK_REQUIRED", "TIMING_VALID_NOT_FINAL", "BASKET_THEME_CONFIRMATION_CONTEXT", "JPY_ALIGNMENT_REQUIRED"]},
    "USDJPY": {"default_role": "PHASE_SENSITIVE_JPY_MAJOR", "golden_patterns": ["PHASE_SENSITIVE_BREAKDOWN", "UPPER_ABSORPTION_WARNING", "LIQUIDATION_EXPANSION", "SPARSE_ARCHIVE", "LOWER_RANGE_NO_CHASE_FILTER", "LATE_DENSE_PRESSURE_MANAGEMENT_ALERT", "SIGNAL_LIFECYCLE_CONFLICT_WATCH", "JPY_ALIGNMENT_REQUIRED"]},
    "GBPJPY": {"default_role": "PHASE_SENSITIVE_JPY_CROSS", "golden_patterns": ["MICROBURST_FOLLOWTHROUGH_RECLAIM", "CLEAN_5M_TIMING_GATE_NOT_FINAL", "HIGH_DENSITY_ACCELERATION_CONTINUATION", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "TIMING_VALID_NOT_FINAL", "BASKET_THEME_CONFIRMATION_CONTEXT", "JPY_ALIGNMENT_REQUIRED"]},
    "AUDJPY": {"default_role": "JPY_WEAKNESS_CONFIRMATION_CROSS", "golden_patterns": ["OPEN_LANE_TIMING_VALID", "MICROBURST_FOLLOWTHROUGH_RECLAIM", "HIGH_DENSITY_ACCELERATION_CONTINUATION", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "TIMING_VALID_NOT_FINAL", "BASKET_THEME_CONFIRMATION_CONTEXT", "JPY_ALIGNMENT_REQUIRED"]},
    "NZDCHF": {"default_role": "CHF_CROSS_PHASE_SENSITIVE", "golden_patterns": ["BEARISH_OR_BULLISH_CONTINUATION_AFTER_HOT_BLOCK", "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", "REPEATED_PRESSURE_MANAGEMENT_ALERT"]},
    "EURCHF": {"default_role": "CHF_WEAKNESS_MICROBOOST_CROSS", "golden_patterns": ["COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", "DELAYED_FOLLOWTHROUGH_WATCH", "HIGH_DENSITY_ACCELERATION_CONTINUATION", "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", "BASKET_THEME_CONFIRMATION_CONTEXT"]},
    "EURUSD": {"default_role": "MAJOR_CONTEXT_PAIR", "golden_patterns": ["MAJOR_PAIR_DELAYED_CONTINUATION", "PULLBACK_WITHIN_H4_EXPANSION"]},
    "GBPNZD": {"default_role": "TAKEOVER_CONTEXTUAL_CROSS", "golden_patterns": ["SAME_PAIR_TAKEOVER", "SAME_PAIR_TAKEOVER_GRIND", "TAKEOVER_TO_LATE_REVERSAL", "CHOPPY_TAKEOVER_CONTINUATION", "DAILY_CONFLICT_AFTER_INTRADAY_TAKEOVER"]},
    "USDCAD": {"default_role": "MACRO_ANCHOR_AND_SIGNALWATCH_LIFECYCLE", "golden_patterns": ["SLOW_ACTIVE_SIGNAL_SEED", "SIGNALWATCH_LIFECYCLE_FINALIZER", "ABSORPTION_WATCH_FAILED", "HIGH_DENSITY_ABSORPTION_WITH_RECLAIM", "SIGNAL_LIFECYCLE_CONFLICT_WATCH"]},
    "XAUUSD": {"default_role": "METAL_VOLATILITY_LIFECYCLE", "golden_patterns": ["METAL_SUSTAINED_PRESSURE_CONTEXT", "METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", "METAL_EXTENDED_MFE_THEN_REVERSAL", "METAL_NO_CHASE_AFTER_UPPER_SPIKE"]},
    "XAGUSD": {"default_role": "HIGH_VOLATILITY_METAL_PRESSURE_REFERENCE", "golden_patterns": ["METAL_PRESSURE_BROAD_FOLLOWTHROUGH_BUT_BLOCK_WHIPSAW", "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM", "METAL_SUSTAINED_PRESSURE_CONTEXT", "METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", "METAL_EXTENDED_MFE_THEN_REVERSAL", "METAL_NO_CHASE_AFTER_UPPER_SPIKE"]},
    "EURAUD": {"default_role": "MULTI_WAVE_PRIORITY_PAIR", "golden_patterns": ["MULTI_WAVE_PRIORITY", "CLEAN_SAME_PAIR_TAKEOVER", "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", "TIMING_VALID_NOT_FINAL"]},
    # Tier A candidate reference pool — schema v2
    "CHFJPY": {"default_role": "JPY_CHF_DUAL_BASKET_CROSS", "golden_patterns": ["BASKET_THEME_CONFIRMATION_CONTEXT", "JPY_BASKET_THEME_FOLLOWTHROUGH", "FRAGMENTED_BASKET_ROTATION_NOT_ENTRY", "MTF_BULLISH_PULLBACK_DECISION", "LATE_SESSION_EXPANSION_FAIL", "HIGH_DENSITY_ACCELERATION_CONTINUATION", "TIMING_VALID_NOT_FINAL", "JPY_ALIGNMENT_REQUIRED"]},
    "NZDJPY": {"default_role": "JPY_BASKET_SECONDARY_CONFIRMATION", "golden_patterns": ["BASKET_THEME_CONFIRMATION_CONTEXT", "JPY_BASKET_SECONDARY_CONFIRMATION", "FRAGMENTED_THEME_FOLLOWTHROUGH", "DELAYED_JPY_CROSS_CONTINUATION", "MACRO_BULLISH_INTRADAY_PULLBACK_DECISION", "POST_EXPANSION_NO_CHASE_FILTER", "TIMING_VALID_NOT_FINAL", "JPY_ALIGNMENT_REQUIRED"]},
    "GBPUSD": {"default_role": "GBP_THEME_MAJOR_CONFIRMATION", "golden_patterns": ["LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", "LOW_DENSITY_MAJOR_PAIR_CONTINUATION", "BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY", "DELAYED_GBP_CONTINUATION_AFTER_WAIT", "MAJOR_PAIR_POST_EXPANSION_NO_CHASE", "TIMING_VALID_NOT_FINAL"]},
    "EURNZD": {"default_role": "SUPPORTING_EUR_CROSS_FALSE_CONTINUATION_REFERENCE", "golden_patterns": ["SUPPORTING_EUR_CROSS_NOT_LEADER", "EURNZD_UPPER_FADE_AFTER_EUR_CROSS_PRESSURE", "CROSS_THEME_LEADER_DIVERGENCE", "MACRO_BEARISH_INTRADAY_REPAIR_DECISION", "SUPPORTING_CROSS_NOT_PRIMARY_LEADER", "TIMING_VALID_NOT_FINAL"]},
    "AUDNZD": {"default_role": "LOW_DENSITY_BLOCK_FALSE_CONTINUATION_REFERENCE", "golden_patterns": ["LOW_DENSITY_BLOCK_FALSE_CONTINUATION", "AUDNZD_RELATIVE_STRENGTH_DECISION_PAIR", "SUPPORTING_CROSS_NOT_PRIMARY_LEADER", "BULLISH_REPAIR_UPPER_DECISION_NO_CHASE"]},
    "GBPAUD": {"default_role": "GBP_AUD_VOLATILITY_CROSS", "golden_patterns": ["CLEAN_SAME_PAIR_TAKEOVER", "TIMING_VALID_NOT_FINAL"]},
    "EURGBP": {"default_role": "SUPPORTING_EUR_CROSS_FILTER", "golden_patterns": ["SUPPORTING_EUR_CROSS_NOT_LEADER", "EURGBP_RANGE_COMPRESSION_FILTER", "SUPPORTING_CROSS_NOT_PRIMARY_LEADER", "TIMING_VALID_NOT_FINAL"]},
    "AUDUSD": {"default_role": "AUD_STRENGTH_USD_WEAKNESS_FOLLOWTHROUGH_REFERENCE", "golden_patterns": ["AUDUSD_LOW_DRAWDOWN_BULLISH_FOLLOWTHROUGH", "AUDUSD_POST_REJECTION_RECOVERY_FILTER", "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", "MAJOR_PAIR_POST_EXPANSION_NO_CHASE", "TIMING_VALID_NOT_FINAL"]},
    "AUDCHF": {"default_role": "CHF_WEAKNESS_CONFIRMATION_PAIR", "golden_patterns": ["CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH", "AUDCHF_BULLISH_ALIGNMENT_UPPER_NO_CHASE", "BASKET_THEME_CONFIRMATION_CONTEXT", "SUPPORTING_CROSS_NOT_PRIMARY_LEADER", "TIMING_VALID_NOT_FINAL"]},
}

_STATIC_SCORING_MODEL: dict[str, Any] = {
    "max_score": 100,
    "tier_weights": {
        "S+": 55,
        "S": 50,
        "S-": 45,
        "A+": 40,
        "A": 35,
        "A-": 30,
        "B+": 25,
        "B": 20,
        "B-": 15,
    },
    "penalties": {
        "theme_conflict_penalty": -35,
        "incomplete_tradeplan_penalty": -40,
        "sparse_archive_penalty": -50,
        "late_chase_penalty": -25,
    },
}


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    if yaml is None or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except (OSError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_patterns_from_yaml() -> tuple[GoldenPattern, ...] | None:
    payload = _load_yaml_file(Path(__file__).with_name("pattern_registry.yaml"))
    raw_patterns = None if payload is None else payload.get("patterns")
    if not isinstance(raw_patterns, list):
        return None
    patterns: list[GoldenPattern] = []
    seen: set[str] = set()
    for item in raw_patterns:
        if not isinstance(item, dict):
            return None
        pattern = _pattern_from_yaml(item)
        if pattern is None or pattern.pattern_id in seen:
            return None
        seen.add(pattern.pattern_id)
        patterns.append(pattern)
    return tuple(patterns) if patterns else None


def _pattern_from_yaml(item: dict[str, Any]) -> GoldenPattern | None:
    required = ("pattern_id", "tier", "family", "golden_source", "function", "entry_permission")
    if any(not str(item.get(key) or "").strip() for key in required):
        return None
    return GoldenPattern(
        pattern_id=str(item["pattern_id"]).strip().upper(),
        tier=str(item["tier"]).strip(),
        family=str(item["family"]).strip().upper(),
        golden_source=str(item["golden_source"]).strip().upper(),
        function=str(item["function"]).strip(),
        entry_permission=str(item["entry_permission"]).strip().upper(),
        management_action=_optional_text(item.get("management_action")),
        hold_policy=_optional_text(item.get("hold_policy")),
        chase_allowed=bool(item.get("chase_allowed", False)),
        block_reason=_optional_text(item.get("block_reason")),
        scope=str(item.get("scope") or "UNIVERSAL").strip().upper(),
        applies_to=str(item.get("applies_to") or "ALL_PAIRS_IF_CONDITIONS_MATCH").strip().upper(),
        golden_references=tuple(_string_list(item.get("golden_references")) or ()),
        pair_specific_calibration=tuple(_string_list(item.get("pair_specific_calibration")) or ()),
    )


def _load_pair_role_map_from_yaml() -> dict[str, dict[str, Any]] | None:
    payload = _load_yaml_file(Path(__file__).with_name("pair_role_map.yaml"))
    raw_map = None if payload is None else payload.get("pair_role_map")
    if not isinstance(raw_map, dict):
        return None
    role_map: dict[str, dict[str, Any]] = {}
    for symbol, config in raw_map.items():
        if not isinstance(config, dict):
            return None
        default_role = _optional_text(config.get("default_role"))
        golden_patterns = _string_list(config.get("golden_patterns"))
        if default_role is None or golden_patterns is None:
            return None
        role_map[str(symbol).strip().upper()] = {
            "default_role": default_role,
            "golden_patterns": golden_patterns,
        }
    return role_map or None


def _load_scoring_model_from_yaml() -> dict[str, Any] | None:
    payload = _load_yaml_file(Path(__file__).with_name("scoring_model.yaml"))
    model = None if payload is None else payload.get("scoring_model")
    return dict(model) if isinstance(model, dict) else None


def _load_routing_logic_from_yaml() -> dict[str, Any] | None:
    payload = _load_yaml_file(Path(__file__).with_name("routing_logic.yaml"))
    router = None if payload is None else payload.get("pattern_router")
    return dict(router) if isinstance(router, dict) else None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.upper() if text else None


def _string_list(value: Any) -> list[str] | None:
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip().upper() for item in value if str(item or "").strip()]
        return items or None
    text = str(value or "").strip()
    return [text.upper()] if text else None


_YAML_GOLDEN_PATTERNS = _load_patterns_from_yaml()
_YAML_PAIR_ROLE_MAP = _load_pair_role_map_from_yaml()
_YAML_SCORING_MODEL = _load_scoring_model_from_yaml()
_YAML_ROUTING_LOGIC = _load_routing_logic_from_yaml()

GOLDEN_PATTERNS: tuple[GoldenPattern, ...] = _YAML_GOLDEN_PATTERNS or _STATIC_GOLDEN_PATTERNS
PAIR_ROLE_MAP: dict[str, dict[str, Any]] = _YAML_PAIR_ROLE_MAP or _STATIC_PAIR_ROLE_MAP
SCORING_MODEL: dict[str, Any] = _YAML_SCORING_MODEL or _STATIC_SCORING_MODEL
ROUTING_LOGIC: dict[str, Any] = _YAML_ROUTING_LOGIC or {}
REGISTRY_SOURCE: dict[str, str] = {
    "patterns": "yaml" if _YAML_GOLDEN_PATTERNS is not None else "static",
    "pair_roles": "yaml" if _YAML_PAIR_ROLE_MAP is not None else "static",
    "scoring_model": "yaml" if _YAML_SCORING_MODEL is not None else "static",
    "routing_logic": "yaml" if _YAML_ROUTING_LOGIC is not None else "missing",
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
