"""Market-context validation for SignalThrottle candidates.

This module is intentionally conservative.  It validates a candidate only when
the caller supplies price snapshots, phase, and spread context.
It never fetches market data and never fabricates missing prices.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from analysis.signal_throttle_pattern_detector import MarketPatternDecision, classify_market_pattern
from analysis.signalthrottle_patterns import match_golden_patterns
from schemas.direction import normalize_direction

_BULLISH_M15_PHASES = {
    "PIVOT_RECLAIM",
    "BULLISH_PULLBACK",
    "BREAKOUT_RETEST",
    "SUPPORT_HOLD",
    "HIGH_BASE_CONTINUATION",
    "BULLISH_TREND",
    "BULLISH_UPPER_RANGE_CONTINUATION",
    "UPPER_BREAKOUT_CONTINUATION",
}
_BEARISH_M15_PHASES = {
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
}
_BULLISH_H1_PHASES = {"BULLISH", "BULLISH_PULLBACK", "UPTREND", "ACCUMULATION_RECLAIM", "BULLISH_TREND"}
_BEARISH_H1_PHASES = {
    "BEARISH",
    "BEARISH_PULLBACK",
    "DOWNTREND",
    "DISTRIBUTION_BREAKDOWN",
    "BEARISH_TREND",
    "BEARISH_PULLBACK_OR_BREAKDOWN",
}


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    raw_allowed_direction: str | None
    bid: float | None = None
    ask: float | None = None
    pip_value: float | None = None
    price_at_signal_start: float | None = None
    price_at_5m_confirm: float | None = None
    price_at_signal_end: float | None = None
    m15_phase: str | None = None
    h1_phase: str | None = None
    h4_phase: str | None = None
    # Step 1 — HTF Daily Phase Feed. Populated only when HTF_DAILY_PHASE_FEED_ENABLED=true
    # (default None preserves legacy behavior). Read by the golden-pattern matcher's
    # dormant Daily-aware rules via asdict(context). Never a hard execution blocker.
    d1_phase: str | None = None
    theme_aligned: bool | None = None
    theme_alignment: str | None = None
    counter_entry_theme_alignment: str | None = None
    jpy_alignment_status: str | None = None
    jpy_alignment: str | None = None
    dual_theme_status: str | None = None
    spread_normal: bool | None = None
    spread_pips: float | None = None
    max_allowed_spread_pips: float | None = None
    market_bias: str | None = None
    trend_direction: str | None = None
    price_position: str | None = None
    main_support: float | None = None
    main_resistance: float | None = None
    key_support: float | None = None
    key_resistance: float | None = None
    buy_pullback_low: float | None = None
    buy_pullback_high: float | None = None
    breakout_retest_low: float | None = None
    breakout_retest_high: float | None = None
    sell_rejection_low: float | None = None
    sell_rejection_high: float | None = None
    range_position: float | None = None
    is_late_pressure: bool = False
    resistance_low: float | None = None
    resistance_high: float | None = None
    minor_support: float | None = None
    major_support: float | None = None
    m15_close: float | None = None
    m15_open: float | None = None
    m15_high: float | None = None
    m15_low: float | None = None
    m15_range_atr_ratio: float | None = None
    m15_body_atr_ratio: float | None = None
    m15_close_above_resistance: bool | None = None
    m15_breakout_retest_held: bool | None = None
    m15_rejection_from_resistance: bool | None = None
    m15_close_below_minor_support: bool | None = None
    support_low: float | None = None
    support_high: float | None = None
    minor_resistance: float | None = None
    m15_close_below_support: bool | None = None
    m15_breakdown_retest_held: bool | None = None
    m15_rejection_from_support: bool | None = None
    m15_close_above_minor_resistance: bool | None = None
    sl_buffer: float | None = None
    sl_safe: float | None = None
    continuation_sl_safe: float | None = None
    tp1_support: float | None = None
    tp2_support: float | None = None
    tp3_support: float | None = None
    tp4_support: float | None = None
    tp1_resistance: float | None = None
    tp2_resistance: float | None = None
    tp3_resistance: float | None = None
    tp4_resistance: float | None = None
    m15_bar_count: int | None = None
    h1_bar_count: int | None = None
    support_ladder_ready: bool | None = None
    resistance_ladder_ready: bool | None = None
    tradeplan_context_ready: bool | None = None
    support_ladder_missing_reason: str | None = None
    resistance_ladder_missing_reason: str | None = None
    structure_atr_ratio: float | None = None
    h4_atr_ratio: float | None = None
    d1_atr_ratio: float | None = None
    structure_close_pos: float | None = None
    h4_close_pos: float | None = None
    d1_close_pos: float | None = None
    reclaim_confirmed: bool | None = None
    breakdown_confirmed: bool | None = None
    price_confirmation: bool | None = None
    price_context_complete: bool | None = None
    theme_context_only: bool | None = None
    lower_timeframe_confirmation: bool | None = None
    fragmented_run: bool | None = None
    weak_individual_run: bool | None = None
    forward_mfe_pips: float | None = None
    forward_mae_pips: float | None = None
    mfe_pips: float | None = None
    mae_pips: float | None = None
    mfe_mae_symmetry_risk: bool | None = None
    chase_rr_poor: bool | None = None
    near_recent_high_low_without_breakout_close: bool | None = None
    structure_candle_strong_close: bool | None = None
    continuation_context: bool | None = None


@dataclass(frozen=True)
class MarketContextValidation:
    symbol: str
    raw_allowed_direction: str | None
    final_direction: str
    direction_validated: bool
    execution_grade: str
    action: str
    requires_market_context: bool
    reason: str
    strategy_pattern: str = "PRICE_PHASE_UNRESOLVED"
    phase_grade: str = "UNRESOLVED"
    execution_side: str = "WAIT"
    priority: str = "WATCH_NEUTRAL"
    waiting_for: str | None = "M15_H1_PHASE_AND_STRUCTURE_CONFIRMATION"
    requires_confirmation: bool = True
    matched_patterns: list[str] | None = None
    selected_pattern_id: str | None = None
    pattern_tier: str | None = None
    pattern_family: str | None = None
    pattern_score: int = 0
    pattern_match_score: int = 0
    execution_readiness_score: int = 0
    golden_reference: str | None = None
    pattern_scope: str | None = None
    applies_to: str | None = None
    golden_references: list[str] | None = None
    pair_specific_calibration: list[str] | None = None
    pair_role: str | None = None
    entry_permission: str | None = None
    management_action: str | None = None
    hold_policy: str | None = None
    chase_allowed: bool = False
    block_reason: str | None = None
    pattern_evidence: list[str] | None = None
    jpy_alignment_status: str | None = None
    theme_alignment_status: str | None = None
    dual_theme_status: str | None = None
    alignment_missing_reason: str | None = None
    pattern_search_space: list[str] | None = None
    pattern_db_candidates_scanned: int | None = None
    pattern_db_exact_matches: list[str] | None = None
    pattern_db_fuzzy_matches: list[str] | None = None
    pattern_bottlenecks: list[str] | None = None
    pattern_match_diagnostics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_market_context(context: MarketContext) -> MarketContextValidation:
    direction = normalize_direction(context.raw_allowed_direction)
    if direction is None:
        return _result(context, "WAIT", False, "UNVALIDATED", "WAIT", True, "raw_direction_missing")

    missing = _missing_fields(context)
    if missing:
        return _result(
            context,
            "WAIT",
            False,
            "UNVALIDATED",
            "FETCH_MARKET_CONTEXT",
            True,
            f"missing_market_context={','.join(missing)}",
        )

    if context.is_late_pressure:
        return _result(
            context,
            "NO_NEW_ENTRY",
            False,
            "PROTECT",
            "PROTECT_PROFIT",
            False,
            "late_pressure_no_chase",
        )

    if context.spread_normal is False:
        return _result(
            context,
            "WAIT",
            False,
            "BLOCKED",
            "WAIT_SPREAD_NORMALIZATION",
            False,
            "spread_not_normal",
        )

    pattern = classify_market_pattern(context, direction=direction)
    if pattern.final_direction == "NO_NEW_ENTRY":
        return _result(
            context,
            "NO_NEW_ENTRY",
            False,
            pattern.execution_grade,
            pattern.action,
            False,
            pattern.reason,
            pattern=pattern,
        )

    if direction == "BUY" and _buy_context_valid(context):
        action, reason = _validated_action_reason(
            context,
            pattern,
            default_action="BUY_ON_PULLBACK",
            default_reason="price_phase_aligned",
        )
        return _result(
            context,
            "BUY",
            True,
            pattern.execution_grade if pattern.final_direction == "BUY" else "A-",
            action,
            False,
            reason,
            pattern=pattern,
        )

    if direction == "SELL" and _sell_context_valid(context):
        action, reason = _validated_action_reason(
            context,
            pattern,
            default_action="SELL_ON_PULLBACK",
            default_reason="price_phase_aligned",
        )
        return _result(
            context,
            "SELL",
            True,
            pattern.execution_grade if pattern.final_direction == "SELL" else "A-",
            action,
            False,
            reason,
            pattern=pattern,
        )

    if pattern.strategy_pattern != "PRICE_PHASE_UNRESOLVED":
        return _result(
            context,
            "WAIT",
            False,
            pattern.execution_grade,
            pattern.action,
            False,
            pattern.reason,
            pattern=pattern,
        )

    return _result(
        context,
        "WAIT",
        False,
        "UNVALIDATED",
        "WAIT_PRICE_PHASE_ALIGNMENT",
        False,
        "price_or_phase_not_aligned",
    )


def missing_market_context_result(symbol: str, raw_allowed_direction: str | None = None) -> MarketContextValidation:
    return validate_market_context(MarketContext(symbol=symbol, raw_allowed_direction=raw_allowed_direction))


def _buy_context_valid(context: MarketContext) -> bool:
    return (
        float(context.price_at_5m_confirm or 0.0) >= float(context.price_at_signal_start or 0.0)
        and float(context.price_at_signal_end or 0.0) >= float(context.price_at_signal_start or 0.0)
        and _phase(context.m15_phase) in _BULLISH_M15_PHASES
        and _phase(context.h1_phase) in _BULLISH_H1_PHASES
    )


def _sell_context_valid(context: MarketContext) -> bool:
    return (
        float(context.price_at_5m_confirm or 0.0) <= float(context.price_at_signal_start or 0.0)
        and float(context.price_at_signal_end or 0.0) <= float(context.price_at_signal_start or 0.0)
        and _phase(context.m15_phase) in _BEARISH_M15_PHASES
        and _phase(context.h1_phase) in _BEARISH_H1_PHASES
    )


def _missing_fields(context: MarketContext) -> list[str]:
    missing: list[str] = []
    for name in (
        "price_at_signal_start",
        "price_at_5m_confirm",
        "price_at_signal_end",
        "m15_phase",
        "h1_phase",
        "spread_normal",
    ):
        if getattr(context, name) is None:
            missing.append(name)
    return missing


def _phase(value: str | None) -> str:
    return str(value or "").strip().upper()


def _result(
    context: MarketContext,
    final_direction: str,
    direction_validated: bool,
    execution_grade: str,
    action: str,
    requires_market_context: bool,
    reason: str,
    *,
    pattern: MarketPatternDecision | None = None,
) -> MarketContextValidation:
    pattern = pattern or classify_market_pattern(context, direction=context.raw_allowed_direction)
    golden = match_golden_patterns(
        _golden_pattern_features(
            context,
            pattern,
            final_direction=final_direction,
            direction_validated=direction_validated,
            execution_grade=execution_grade,
            action=action,
            requires_market_context=requires_market_context,
            reason=reason,
        )
    )
    return MarketContextValidation(
        symbol=context.symbol,
        raw_allowed_direction=normalize_direction(context.raw_allowed_direction),
        final_direction=final_direction,
        direction_validated=direction_validated,
        execution_grade=execution_grade,
        action=action,
        requires_market_context=requires_market_context,
        reason=reason,
        strategy_pattern=pattern.strategy_pattern,
        phase_grade=pattern.phase_grade,
        execution_side=pattern.execution_side,
        priority=pattern.strategy_priority,
        waiting_for=pattern.waiting_for,
        requires_confirmation=pattern.requires_confirmation,
        matched_patterns=_string_list(golden.get("matched_patterns")),
        selected_pattern_id=_optional_text(golden.get("selected_pattern_id")),
        pattern_tier=_optional_text(golden.get("pattern_tier")),
        pattern_family=_optional_text(golden.get("pattern_family")),
        pattern_score=int(golden.get("pattern_score") or 0),
        pattern_match_score=int(golden.get("pattern_match_score") or 0),
        execution_readiness_score=int(golden.get("execution_readiness_score") or 0),
        golden_reference=_optional_text(golden.get("golden_reference")),
        pattern_scope=_optional_text(golden.get("pattern_scope")),
        applies_to=_optional_text(golden.get("applies_to")),
        golden_references=_string_list(golden.get("golden_references")),
        pair_specific_calibration=_string_list(golden.get("pair_specific_calibration")),
        pair_role=_optional_text(golden.get("pair_role")),
        entry_permission=_optional_text(golden.get("entry_permission")),
        management_action=_optional_text(golden.get("management_action")),
        hold_policy=_optional_text(golden.get("hold_policy")),
        chase_allowed=bool(golden.get("chase_allowed", False)),
        block_reason=_optional_text(golden.get("block_reason")),
        pattern_evidence=_string_list(golden.get("pattern_evidence")),
        jpy_alignment_status=_optional_text(golden.get("jpy_alignment_status")),
        theme_alignment_status=_optional_text(golden.get("theme_alignment_status")),
        dual_theme_status=_optional_text(golden.get("dual_theme_status")),
        alignment_missing_reason=_optional_text(golden.get("alignment_missing_reason")),
        pattern_search_space=_string_list(golden.get("pattern_search_space")),
        pattern_db_candidates_scanned=_optional_int(golden.get("pattern_db_candidates_scanned")),
        pattern_db_exact_matches=_string_list(golden.get("pattern_db_exact_matches")),
        pattern_db_fuzzy_matches=_string_list(golden.get("pattern_db_fuzzy_matches")),
        pattern_bottlenecks=_string_list(golden.get("pattern_bottlenecks")),
        pattern_match_diagnostics=_dict_value(golden.get("pattern_match_diagnostics")),
    )


def _golden_pattern_features(
    context: MarketContext,
    pattern: MarketPatternDecision,
    *,
    final_direction: str,
    direction_validated: bool,
    execution_grade: str,
    action: str,
    requires_market_context: bool,
    reason: str,
) -> dict[str, Any]:
    features = asdict(context)
    features.update(pattern.to_dict())
    features.update(
        {
            "final_direction": final_direction,
            "direction_validated": direction_validated,
            "execution_grade": execution_grade,
            "action": action,
            "requires_market_context": requires_market_context,
            "reason": reason,
        }
    )
    return features


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [str(item) for item in value if str(item or "").strip()]
    return values or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dict_value(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _validated_action_reason(
    context: MarketContext,
    pattern: MarketPatternDecision,
    *,
    default_action: str,
    default_reason: str,
) -> tuple[str, str]:
    specific_patterns = {
        "BULLISH_UPPER_RANGE_CONTINUATION",
        "BEARISH_BREAKDOWN_CASCADE",
        "BEARISH_LIQUIDATION_EXPANSION",
        "CLEAN_BEARISH_CONTINUATION_PRESSURE",
        "LOWER_RANGE_SELL_EXHAUSTION",
        "UPPER_RANGE_EXHAUSTION",
        "UPPER_ABSORPTION_WARNING",
    }
    if pattern.strategy_pattern in specific_patterns or context.price_position is not None:
        return pattern.action, pattern.reason
    return default_action, default_reason
