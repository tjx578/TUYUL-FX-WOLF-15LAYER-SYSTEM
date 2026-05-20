"""Market-context validation for SignalThrottle candidates.

This module is intentionally conservative.  It validates a candidate only when
the caller supplies price snapshots, theme alignment, phase, and spread context.
It never fetches market data and never fabricates missing prices.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from schemas.direction import normalize_direction

_BULLISH_M15_PHASES = {
    "PIVOT_RECLAIM",
    "BULLISH_PULLBACK",
    "BREAKOUT_RETEST",
    "SUPPORT_HOLD",
    "HIGH_BASE_CONTINUATION",
}
_BEARISH_M15_PHASES = {
    "BREAKDOWN_RETEST",
    "BEARISH_PULLBACK",
    "RESISTANCE_REJECTION",
    "LOWER_HIGH",
    "SUPPORT_BREAK",
}
_BULLISH_H1_PHASES = {"BULLISH", "BULLISH_PULLBACK", "UPTREND", "ACCUMULATION_RECLAIM"}
_BEARISH_H1_PHASES = {"BEARISH", "BEARISH_PULLBACK", "DOWNTREND", "DISTRIBUTION_BREAKDOWN"}


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
    theme_aligned: bool | None = None
    theme_alignment: str | None = None
    counter_entry_theme_alignment: str | None = None
    spread_normal: bool | None = None
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
    m15_close_above_resistance: bool | None = None
    m15_rejection_from_resistance: bool | None = None
    m15_close_below_minor_support: bool | None = None
    support_low: float | None = None
    support_high: float | None = None
    minor_resistance: float | None = None
    m15_close_below_support: bool | None = None
    m15_rejection_from_support: bool | None = None
    m15_close_above_minor_resistance: bool | None = None
    sl_buffer: float | None = None
    sl_tight: float | None = None
    sl_safe: float | None = None
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

    if context.theme_aligned is False:
        return _result(
            context,
            "BLOCK_DIRECTION",
            False,
            "BLOCKED",
            "BLOCK_ENTRY",
            False,
            "theme_mismatch",
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

    if direction == "BUY" and _buy_context_valid(context):
        return _result(context, "BUY", True, "A-", "BUY_ON_PULLBACK", False, "price_theme_phase_aligned")

    if direction == "SELL" and _sell_context_valid(context):
        return _result(context, "SELL", True, "A-", "SELL_ON_PULLBACK", False, "price_theme_phase_aligned")

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
        "theme_aligned",
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
) -> MarketContextValidation:
    return MarketContextValidation(
        symbol=context.symbol,
        raw_allowed_direction=normalize_direction(context.raw_allowed_direction),
        final_direction=final_direction,
        direction_validated=direction_validated,
        execution_grade=execution_grade,
        action=action,
        requires_market_context=requires_market_context,
        reason=reason,
    )
