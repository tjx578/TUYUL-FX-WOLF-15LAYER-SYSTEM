"""Pattern detection helpers for SignalThrottle pressure.

SignalThrottle pressure is telemetry, not a final side.  These helpers keep the
pressure quality and the market-structure interpretation separate so live
callers can promote a radar event into BUY, SELL, PROTECT, or ARCHIVE only when
the price phase supports that interpretation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any


@dataclass(frozen=True)
class PressureBlockProfile:
    pressure_grade: str
    pressure_temperature: str
    priority: str
    signal_status: str
    max_gap_health: str
    execution_status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketPatternDecision:
    strategy_pattern: str
    phase_grade: str
    execution_side: str
    strategy_priority: str
    final_direction: str
    execution_grade: str
    action: str
    waiting_for: str
    requires_confirmation: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_pressure_block(
    *,
    duration_seconds: float,
    event_count: int,
    density_per_minute: float,
    max_gap_seconds: float,
) -> PressureBlockProfile:
    """Classify raw pressure quality without assigning trade direction."""
    duration = max(0.0, float(duration_seconds or 0.0))
    events = max(0, int(event_count or 0))
    density = max(0.0, float(density_per_minute or 0.0))
    gap = max(0.0, float(max_gap_seconds or 0.0))
    gap_health = _gap_health(gap)

    if events <= 3 and density < 0.5:
        return PressureBlockProfile(
            pressure_grade="D",
            pressure_temperature="SPARSE_ARCHIVE",
            priority="ARCHIVE_ONLY",
            signal_status="ARCHIVE_ONLY",
            max_gap_health=gap_health,
            execution_status="NO_TRADE",
            reason="very_low_event_count_and_density",
        )

    if duration >= 300.0 and events >= 30 and density >= 8.0 and gap <= 120.0:
        return PressureBlockProfile(
            pressure_grade="A+",
            pressure_temperature="HIGH_DENSITY_ACTIVE_PRESSURE",
            priority="WATCH_HIGH",
            signal_status="FULL_CLEAN_PRESSURE_BLOCK",
            max_gap_health=gap_health,
            execution_status="WAIT_CHART_PHASE_AND_CONFIRMATION",
            reason="duration_events_density_and_gap_confirm_active_pressure",
        )

    if duration >= 300.0 and events >= 30 and density >= 4.0 and gap <= 120.0:
        return PressureBlockProfile(
            pressure_grade="B_PLUS_TO_A_MINUS",
            pressure_temperature="ACTIVE_PRESSURE",
            priority="WATCH_HIGH",
            signal_status="ACTIVE_PRESSURE_RADAR",
            max_gap_health=gap_health,
            execution_status="WAIT_CHART_PHASE_AND_CONFIRMATION",
            reason="active_pressure_block_matches_usdjpy_r5_profile",
        )

    if duration >= 300.0 and events >= 10 and density >= 3.0:
        return PressureBlockProfile(
            pressure_grade="B",
            pressure_temperature="TACTICAL_PRESSURE",
            priority="WATCH_MEDIUM",
            signal_status="TACTICAL_RADAR",
            max_gap_health=gap_health,
            execution_status="WAIT_M15_CONFIRMATION",
            reason="valid_duration_with_tactical_density",
        )

    if duration >= 300.0 and events >= 10:
        return PressureBlockProfile(
            pressure_grade="C",
            pressure_temperature="CONTEXTUAL_RADAR",
            priority="WATCH_LOW",
            signal_status="VALID_CONTEXTUAL_RADAR",
            max_gap_health=gap_health,
            execution_status="NO_DIRECT_ENTRY",
            reason="duration_or_events_present_but_density_is_contextual",
        )

    if duration >= 60.0 and events >= 5 and density >= 3.0:
        return PressureBlockProfile(
            pressure_grade="C+",
            pressure_temperature="COMPACT_RADAR",
            priority="WATCH_LOW",
            signal_status="VALID_COMPACT_RADAR",
            max_gap_health=gap_health,
            execution_status="WAIT_CHART_PHASE",
            reason="compact_pressure_requires_phase_confirmation",
        )

    return PressureBlockProfile(
        pressure_grade="C-",
        pressure_temperature="LOW_ACTIVITY_RADAR",
        priority="WATCH_LOW",
        signal_status="LOW_ACTIVITY",
        max_gap_health=gap_health,
        execution_status="WAIT_FOR_CLEAN_PRESSURE",
        reason="pressure_not_mature_enough_for_execution_watch",
    )


def classify_market_pattern(
    context: Any,
    *,
    direction: str | None,
    pressure_grade: str | None = None,
) -> MarketPatternDecision:
    """Translate priced market context into a directional strategy pattern."""
    raw_direction = _normalize_direction(direction)
    m15_phase = _phase(_get(context, "m15_phase"))
    h1_phase = _phase(_get(context, "h1_phase"))
    h4_phase = _phase(_get(context, "h4_phase"))
    m15_direction = _m15_direction(m15_phase)
    h1_direction = _h1_direction(h1_phase)
    h4_direction = _h1_direction(h4_phase)
    trend_direction = _normalize_direction(_get(context, "trend_direction")) or h1_direction or h4_direction
    market_bias = _normalize_direction(_get(context, "market_bias"))
    position = _normalize_position(_get(context, "price_position"))
    range_position = _optional_float(_get(context, "range_position"))
    range_atr = _optional_float(_get(context, "m15_range_atr_ratio"))
    body_atr = _optional_float(_get(context, "m15_body_atr_ratio"))
    bearish_mtf = _bearish_count(m15_direction, h1_direction, h4_direction, trend_direction, market_bias) >= 2
    bullish_mtf = _bullish_count(m15_direction, h1_direction, h4_direction, trend_direction, market_bias) >= 2
    at_upper = position == "MAIN_RESISTANCE" or (range_position is not None and range_position >= 0.88)
    at_lower = position == "MAIN_SUPPORT" or (range_position is not None and range_position <= 0.18)
    close_above_resistance = bool(_optional_bool(_get(context, "m15_close_above_resistance")))
    breakout_retest_held = bool(_optional_bool(_get(context, "m15_breakout_retest_held")))
    rejection_from_resistance = bool(_optional_bool(_get(context, "m15_rejection_from_resistance")))
    close_below_support = bool(_optional_bool(_get(context, "m15_close_below_support")))
    breakdown_retest_held = bool(_optional_bool(_get(context, "m15_breakdown_retest_held")))
    rejection_from_support = bool(_optional_bool(_get(context, "m15_rejection_from_support")))
    close_below_minor_support = bool(_optional_bool(_get(context, "m15_close_below_minor_support")))
    close_above_minor_resistance = bool(_optional_bool(_get(context, "m15_close_above_minor_resistance")))
    expanded = (range_atr is not None and range_atr >= 2.0) or (body_atr is not None and body_atr >= 1.5)
    extension = _directional_delta(context, raw_direction)
    pressure = str(pressure_grade or "").upper()

    if raw_direction == "BUY" and at_upper and not (close_above_resistance or breakout_retest_held):
        pattern = "UPPER_RANGE_EXHAUSTION" if rejection_from_resistance or extension <= 0 else "UPPER_ABSORPTION_WARNING"
        return MarketPatternDecision(
            strategy_pattern=pattern,
            phase_grade="EXHAUSTION_OR_ABSORPTION",
            execution_side="PROTECT_LONG_OR_SELL_REJECTION",
            strategy_priority="EXIT_OR_REVERSAL_WATCH",
            final_direction="NO_NEW_ENTRY",
            execution_grade="PROTECT",
            action="NO_NEW_BUY_WAIT_SELL_OR_PULLBACK_CONFIRMATION",
            waiting_for="M15_REJECTION_OR_FAILED_BREAKOUT",
            requires_confirmation=True,
            reason="buy_pressure_at_upper_range_without_breakout_is_exhaustion_risk",
        )

    if raw_direction == "BUY" and at_upper and (close_above_resistance or breakout_retest_held) and bullish_mtf:
        return MarketPatternDecision(
            strategy_pattern="BULLISH_UPPER_RANGE_CONTINUATION",
            phase_grade="BREAKOUT_CONTINUATION",
            execution_side="BUY_CONTINUATION",
            strategy_priority="WATCH_HIGH_BUY",
            final_direction="BUY",
            execution_grade="A-",
            action="BUY_BREAKOUT_RETEST_OR_HOLD",
            waiting_for="M15_RETEST_HOLD_OR_CONTINUATION_CLOSE",
            requires_confirmation=False,
            reason="upper_range_pressure_confirmed_by_breakout_or_retest_hold",
        )

    if (
        raw_direction == "SELL"
        and at_lower
        and not (close_below_support or breakdown_retest_held)
        and bearish_mtf
        and not rejection_from_support
        and extension >= 0
    ):
        pattern = (
            "CLEAN_BEARISH_CONTINUATION_PRESSURE"
            if pressure in {"A+", "A", "A-", "B_PLUS_TO_A_MINUS", "B+"}
            else "BEARISH_PULLBACK_SELL_RALLY"
        )
        return MarketPatternDecision(
            strategy_pattern=pattern,
            phase_grade="LOWER_RANGE_TREND_CONTINUATION",
            execution_side="SELL_CONTINUATION",
            strategy_priority="WATCH_HIGH_SELL" if pattern.startswith("CLEAN") else "WATCH_MEDIUM_SELL",
            final_direction="SELL",
            execution_grade="B+",
            action="WAIT_SELL_TRIGGER_OR_RETEST",
            waiting_for="M15_LOWER_HIGH_FAILED_RECLAIM_OR_NEXT_SUPPORT_BREAK",
            requires_confirmation=True,
            reason="lower_range_sell_pressure_still_aligns_with_bearish_mtf_without_bullish_reclaim",
        )

    if raw_direction == "SELL" and at_lower and not (close_below_support or breakdown_retest_held):
        return MarketPatternDecision(
            strategy_pattern="LOWER_RANGE_SELL_EXHAUSTION",
            phase_grade="EXHAUSTION_OR_SUPPORT_ABSORPTION",
            execution_side="PROTECT_SHORT_OR_BUY_REJECTION",
            strategy_priority="EXIT_OR_REVERSAL_WATCH",
            final_direction="NO_NEW_ENTRY",
            execution_grade="PROTECT",
            action="NO_NEW_SELL_WAIT_BUY_OR_BREAKDOWN_CONFIRMATION",
            waiting_for="M15_BREAKDOWN_OR_SUPPORT_REJECTION_RESOLUTION",
            requires_confirmation=True,
            reason="sell_pressure_at_lower_range_without_breakdown_is_support_absorption_risk",
        )

    if raw_direction == "SELL" and bearish_mtf and (close_below_support or breakdown_retest_held):
        if expanded:
            return MarketPatternDecision(
                strategy_pattern="BEARISH_LIQUIDATION_EXPANSION",
                phase_grade="VOLATILITY_EXPANSION_CONTINUATION",
                execution_side="SELL_CONTINUATION",
                strategy_priority="WATCH_HIGH_SELL",
                final_direction="SELL",
                execution_grade="A",
                action="SELL_AFTER_PULLBACK_NO_MARKET_CHASE",
                waiting_for="M15_PULLBACK_OR_BREAKDOWN_RETEST",
                requires_confirmation=False,
                reason="bearish_mtf_breakdown_with_m15_volatility_expansion",
            )
        return MarketPatternDecision(
            strategy_pattern="BEARISH_BREAKDOWN_CASCADE",
            phase_grade="BREAKDOWN_CONTINUATION",
            execution_side="SELL_CONTINUATION",
            strategy_priority="WATCH_HIGH_SELL",
            final_direction="SELL",
            execution_grade="A-",
            action="SELL_RETEST_OR_BREAKDOWN_CONTINUATION",
            waiting_for="M15_LOWER_HIGH_OR_BREAKDOWN_RETEST",
            requires_confirmation=False,
            reason="bearish_mtf_close_below_structure_confirms_breakdown_cascade",
        )

    if raw_direction == "SELL" and bearish_mtf and m15_direction == "SELL":
        pattern = (
            "CLEAN_BEARISH_CONTINUATION_PRESSURE"
            if pressure in {"A+", "A", "A-", "B_PLUS_TO_A_MINUS", "B+"}
            else "BEARISH_PULLBACK_SELL_RALLY"
        )
        return MarketPatternDecision(
            strategy_pattern=pattern,
            phase_grade="TREND_CONTINUATION",
            execution_side="SELL_CONTINUATION",
            strategy_priority="WATCH_HIGH_SELL" if pattern.startswith("CLEAN") else "WATCH_MEDIUM_SELL",
            final_direction="SELL",
            execution_grade="B+",
            action="WAIT_SELL_TRIGGER_OR_RETEST",
            waiting_for="M15_LOWER_HIGH_FAILED_RECLAIM_OR_SUPPORT_BREAK",
            requires_confirmation=True,
            reason="sell_pressure_aligned_with_bearish_m15_h1_phase",
        )

    if raw_direction == "BUY" and bullish_mtf and m15_direction == "BUY":
        return MarketPatternDecision(
            strategy_pattern="BULLISH_CONTINUATION_PRESSURE",
            phase_grade="TREND_CONTINUATION",
            execution_side="BUY_CONTINUATION",
            strategy_priority="WATCH_HIGH_BUY",
            final_direction="BUY",
            execution_grade="B+",
            action="WAIT_BUY_TRIGGER_OR_RETEST",
            waiting_for="M15_HIGHER_LOW_RECLAIM_OR_BREAKOUT_RETEST",
            requires_confirmation=True,
            reason="buy_pressure_aligned_with_bullish_m15_h1_phase",
        )

    if raw_direction == "BUY" and bearish_mtf and (extension < 0 or close_below_minor_support):
        return MarketPatternDecision(
            strategy_pattern="BUY_PRESSURE_COUNTER_TO_BEARISH_PHASE",
            phase_grade="PHASE_MISMATCH",
            execution_side="SELL_CONTINUATION_OR_PROTECT",
            strategy_priority="BLOCK_BUY_SELL_WATCH",
            final_direction="WAIT",
            execution_grade="CONDITIONAL",
            action="BLOCK_BUY_WAIT_SELL_TRIGGER",
            waiting_for="M15_RECLAIM_OR_SELL_BREAKDOWN_CONFIRMATION",
            requires_confirmation=True,
            reason="buy_pressure_failed_against_bearish_mtf_phase",
        )

    if raw_direction == "SELL" and bullish_mtf and (extension < 0 or close_above_minor_resistance):
        return MarketPatternDecision(
            strategy_pattern="SELL_PRESSURE_COUNTER_TO_BULLISH_PHASE",
            phase_grade="PHASE_MISMATCH",
            execution_side="BUY_CONTINUATION_OR_PROTECT",
            strategy_priority="BLOCK_SELL_BUY_WATCH",
            final_direction="WAIT",
            execution_grade="CONDITIONAL",
            action="BLOCK_SELL_WAIT_BUY_TRIGGER",
            waiting_for="M15_RECLAIM_OR_BUY_BREAKOUT_CONFIRMATION",
            requires_confirmation=True,
            reason="sell_pressure_failed_against_bullish_mtf_phase",
        )

    if rejection_from_support and raw_direction == "BUY":
        return MarketPatternDecision(
            strategy_pattern="SUPPORT_BOUNCE_RECLAIM",
            phase_grade="STRUCTURE_REACTION",
            execution_side="BUY_REACTION",
            strategy_priority="WATCH_MEDIUM_BUY",
            final_direction="BUY",
            execution_grade="B",
            action="BUY_ON_RECLAIM_CONFIRMATION",
            waiting_for="M15_RECLAIM_HOLD",
            requires_confirmation=True,
            reason="support_reaction_detected_for_buy_pressure",
        )

    return MarketPatternDecision(
        strategy_pattern="PRICE_PHASE_UNRESOLVED",
        phase_grade="UNRESOLVED",
        execution_side="WAIT",
        strategy_priority="WATCH_NEUTRAL",
        final_direction="WAIT",
        execution_grade="UNVALIDATED",
        action="WAIT_PRICE_PHASE_ALIGNMENT",
        waiting_for="M15_H1_PHASE_AND_STRUCTURE_CONFIRMATION",
        requires_confirmation=True,
        reason="no_specific_signal_throttle_market_pattern_matched",
    )


def _gap_health(max_gap_seconds: float) -> str:
    if max_gap_seconds <= 30.0:
        return "VERY_HEALTHY"
    if max_gap_seconds <= 60.0:
        return "HEALTHY"
    if max_gap_seconds <= 120.0:
        return "INTERMITTENT"
    if max_gap_seconds <= 300.0:
        return "WEAK"
    return "BROKEN_SEQUENCE"


def _get(context: Any, field: str) -> Any:
    if isinstance(context, dict):
        return context.get(field)
    return getattr(context, field, None)


def _phase(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG", "UPTREND", "TREND_UP"}:
        return "BUY"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT", "DOWNTREND", "TREND_DOWN"}:
        return "SELL"
    if text.startswith("EXECUTE") and text.endswith("_BUY"):
        return "BUY"
    if text.startswith("EXECUTE") and text.endswith("_SELL"):
        return "SELL"
    return None


def _normalize_position(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"MAIN_RESISTANCE", "RESISTANCE", "NEAR_RESISTANCE", "UPPER_RANGE"}:
        return "MAIN_RESISTANCE"
    if text in {"MAIN_SUPPORT", "SUPPORT", "NEAR_SUPPORT", "LOWER_RANGE"}:
        return "MAIN_SUPPORT"
    if text in {"MID_RANGE", "VALUE_AREA", "RANGE_MID"}:
        return "MID_RANGE"
    return text or None


def _m15_direction(value: str) -> str | None:
    if value in {
        "PIVOT_RECLAIM",
        "BULLISH_PULLBACK",
        "BREAKOUT_RETEST",
        "SUPPORT_HOLD",
        "HIGH_BASE_CONTINUATION",
        "BULLISH_TREND",
        "BULLISH_UPPER_RANGE_CONTINUATION",
        "UPPER_BREAKOUT_CONTINUATION",
    }:
        return "BUY"
    if value in {
        "BREAKDOWN_RETEST",
        "BEARISH_PULLBACK",
        "RESISTANCE_REJECTION",
        "LOWER_HIGH",
        "SUPPORT_BREAK",
        "BEARISH_TREND",
        "BEARISH_BREAKDOWN",
        "BEARISH_BREAKDOWN_CASCADE",
        "BEARISH_LIQUIDATION_EXPANSION",
        "CLEAN_BEARISH_CONTINUATION_PRESSURE",
        "BEARISH_PULLBACK_OR_BREAKDOWN",
        "LOWER_RANGE_BREAKDOWN",
    }:
        return "SELL"
    return _normalize_direction(value)


def _h1_direction(value: str) -> str | None:
    if value in {"BULLISH", "BULLISH_PULLBACK", "UPTREND", "ACCUMULATION_RECLAIM", "BULLISH_TREND"}:
        return "BUY"
    if value in {
        "BEARISH",
        "BEARISH_PULLBACK",
        "DOWNTREND",
        "DISTRIBUTION_BREAKDOWN",
        "BEARISH_TREND",
        "BEARISH_PULLBACK_OR_BREAKDOWN",
    }:
        return "SELL"
    return _normalize_direction(value)


def _bullish_count(*directions: str | None) -> int:
    return sum(1 for direction in directions if direction == "BUY")


def _bearish_count(*directions: str | None) -> int:
    return sum(1 for direction in directions if direction == "SELL")


def _directional_delta(context: Any, direction: str | None) -> float:
    start = _optional_float(_get(context, "price_at_signal_start"))
    end = _optional_float(_get(context, "price_at_signal_end"))
    if start is None or end is None:
        return 0.0
    if direction == "SELL":
        return start - end
    return end - start


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None
