"""Canonical price-integrity contract for signal construction.

Observed market prices and analytical reference levels intentionally live in
different objects.  A support, resistance, or entry-zone level must therefore
never become the current signal price by field fallback.

This module is pure and has no emitter/router integration.  Callers provide the
quote, the contemporaneous candle range, and the evaluation time explicitly.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

PRICE_CONTEXT_STALE = "PRICE_CONTEXT_STALE"
PRICE_CONTEXT_OUT_OF_RANGE = "PRICE_CONTEXT_OUT_OF_RANGE"


@dataclass(frozen=True)
class ObservedPrice:
    """A timestamped executable quote observed from the market feed."""

    bid: float
    ask: float
    mid: float
    observed_at: datetime


@dataclass(frozen=True)
class ReferencePriceLevels:
    """Analytical levels that are never treated as an observed quote."""

    support: float | None = None
    resistance: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None


@dataclass(frozen=True)
class ObservedPriceRange:
    """Contemporaneous market range used to corroborate the quote."""

    low: float
    high: float


@dataclass(frozen=True)
class SignalPriceContext:
    """Input contract with a structural boundary between quote and levels."""

    symbol: str
    observed: ObservedPrice
    market_range: ObservedPriceRange
    references: ReferencePriceLevels = ReferencePriceLevels()


@dataclass(frozen=True)
class PriceIntegrityPolicy:
    """Freshness and candle-range tolerances for price validation."""

    max_quote_age_seconds: float = 5.0
    max_future_skew_seconds: float = 1.0
    range_buffer: float = 0.0
    include_spread_in_range_buffer: bool = True


@dataclass(frozen=True)
class SignalPriceIntegrityResult:
    symbol: str
    valid: bool
    reason: str | None
    signal_valid_price: float | None
    quote_age_seconds: float | None
    allowed_range_low: float | None
    allowed_range_high: float | None
    observed: ObservedPrice
    references: ReferencePriceLevels

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed"]["observed_at"] = self.observed.observed_at.astimezone(UTC).isoformat()
        return payload


def validate_signal_price_integrity(
    context: SignalPriceContext,
    *,
    evaluated_at: datetime,
    policy: PriceIntegrityPolicy | None = None,
) -> SignalPriceIntegrityResult:
    """Validate quote freshness and consistency with its market range.

    On success, ``signal_valid_price`` is always the observed midpoint.  It is
    never selected from ``ReferencePriceLevels``.
    """

    effective_policy = policy or PriceIntegrityPolicy()
    _validate_policy(effective_policy)

    observed_at = _aware_utc(context.observed.observed_at, field_name="observed_at")
    evaluation_time = _aware_utc(evaluated_at, field_name="evaluated_at")
    quote_age_seconds = (evaluation_time - observed_at).total_seconds()

    if (
        quote_age_seconds > effective_policy.max_quote_age_seconds
        or quote_age_seconds < -effective_policy.max_future_skew_seconds
    ):
        return _result(
            context,
            valid=False,
            reason=PRICE_CONTEXT_STALE,
            signal_valid_price=None,
            quote_age_seconds=quote_age_seconds,
        )

    bid = context.observed.bid
    ask = context.observed.ask
    mid = context.observed.mid
    range_low = context.market_range.low
    range_high = context.market_range.high

    if not _valid_quote_shape(bid=bid, ask=ask, mid=mid) or not _valid_range_shape(
        low=range_low,
        high=range_high,
    ):
        return _result(
            context,
            valid=False,
            reason=PRICE_CONTEXT_OUT_OF_RANGE,
            signal_valid_price=None,
            quote_age_seconds=quote_age_seconds,
        )

    spread = ask - bid
    buffer = effective_policy.range_buffer
    if effective_policy.include_spread_in_range_buffer:
        buffer += spread
    allowed_range_low = range_low - buffer
    allowed_range_high = range_high + buffer

    if not (allowed_range_low <= mid <= allowed_range_high):
        return _result(
            context,
            valid=False,
            reason=PRICE_CONTEXT_OUT_OF_RANGE,
            signal_valid_price=None,
            quote_age_seconds=quote_age_seconds,
            allowed_range_low=allowed_range_low,
            allowed_range_high=allowed_range_high,
        )

    return _result(
        context,
        valid=True,
        reason=None,
        signal_valid_price=mid,
        quote_age_seconds=quote_age_seconds,
        allowed_range_low=allowed_range_low,
        allowed_range_high=allowed_range_high,
    )


def _result(
    context: SignalPriceContext,
    *,
    valid: bool,
    reason: str | None,
    signal_valid_price: float | None,
    quote_age_seconds: float | None,
    allowed_range_low: float | None = None,
    allowed_range_high: float | None = None,
) -> SignalPriceIntegrityResult:
    return SignalPriceIntegrityResult(
        symbol=context.symbol.strip().upper(),
        valid=valid,
        reason=reason,
        signal_valid_price=signal_valid_price,
        quote_age_seconds=quote_age_seconds,
        allowed_range_low=allowed_range_low,
        allowed_range_high=allowed_range_high,
        observed=context.observed,
        references=context.references,
    )


def _valid_quote_shape(*, bid: float, ask: float, mid: float) -> bool:
    if not all(_finite_positive(value) for value in (bid, ask, mid)):
        return False
    return bid <= mid <= ask


def _valid_range_shape(*, low: float, high: float) -> bool:
    if not all(_finite_positive(value) for value in (low, high)):
        return False
    return low <= high


def _finite_positive(value: float) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _validate_policy(policy: PriceIntegrityPolicy) -> None:
    numeric_values = (
        policy.max_quote_age_seconds,
        policy.max_future_skew_seconds,
        policy.range_buffer,
    )
    if any(not math.isfinite(value) or value < 0 for value in numeric_values):
        raise ValueError("price-integrity policy tolerances must be finite and non-negative")
