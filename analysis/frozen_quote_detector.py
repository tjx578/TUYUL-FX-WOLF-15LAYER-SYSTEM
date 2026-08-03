"""Stateful, session-aware detection for live quotes whose value stops moving."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from utils.market_hours import is_forex_market_open

QuoteHealthStatus = Literal[
    "LIVE",
    "INSUFFICIENT_HISTORY",
    "PRICE_FROZEN",
    "MARKET_CLOSED",
    "NOT_APPLICABLE",
    "MISSING",
    "OUT_OF_ORDER",
]


@dataclass(frozen=True, slots=True)
class FrozenQuoteAssessment:
    status: QuoteHealthStatus
    observed_at_utc: datetime
    unchanged_seconds: float
    consecutive_unchanged: int
    execution_blocked: bool
    reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "quote_health_status": self.status,
            "quote_health_observed_at_utc": self.observed_at_utc.isoformat(),
            "quote_unchanged_seconds": round(self.unchanged_seconds, 3),
            "quote_consecutive_unchanged": self.consecutive_unchanged,
            "quote_health_execution_blocked": self.execution_blocked,
            "quote_health_reason": self.reason,
            "quote_health_rule_version": "frozen-quote.v1",
        }


@dataclass(slots=True)
class _QuoteState:
    price: float
    last_observed_at_utc: datetime
    last_changed_at_utc: datetime
    consecutive_unchanged: int


class FrozenQuoteDetector:
    """Detect frozen LIVE_TICK values while excluding closed market periods.

    The detector uses price-change time rather than quote timestamp age.  It
    therefore catches the boundary failure where a feed keeps publishing fresh
    timestamps around one unchanged price.
    """

    def __init__(
        self,
        *,
        frozen_after_seconds: float = 120.0,
        min_unchanged_observations: int = 3,
        relative_tolerance: float = 1e-9,
    ) -> None:
        if frozen_after_seconds <= 0:
            raise ValueError("frozen_after_seconds must be positive")
        if min_unchanged_observations < 2:
            raise ValueError("min_unchanged_observations must be at least 2")
        if relative_tolerance < 0:
            raise ValueError("relative_tolerance cannot be negative")
        self.frozen_after_seconds = float(frozen_after_seconds)
        self.min_unchanged_observations = int(min_unchanged_observations)
        self.relative_tolerance = float(relative_tolerance)
        self._states: dict[str, _QuoteState] = {}

    def observe(
        self,
        *,
        symbol: str,
        price: float | None,
        observed_at: datetime,
        source: str,
        market_open: bool | None = None,
    ) -> FrozenQuoteAssessment:
        at = _utc(observed_at)
        key = str(symbol or "UNKNOWN").strip().upper() or "UNKNOWN"
        source_key = str(source or "UNKNOWN").strip().upper()
        if price is None or price <= 0:
            return self._assessment("MISSING", at, 0.0, 0, True, "QUOTE_PRICE_MISSING")
        if not source_key.startswith("LIVE_TICK"):
            return self._assessment(
                "NOT_APPLICABLE",
                at,
                0.0,
                0,
                False,
                "FROZEN_CHECK_REQUIRES_LIVE_TICK_SOURCE",
            )

        session_open = is_forex_market_open(at) if market_open is None else bool(market_open)
        if not session_open:
            # Reset at the closed boundary so the weekend itself never counts
            # as unchanged time when the first Sunday/Monday quote arrives.
            self._states.pop(key, None)
            return self._assessment("MARKET_CLOSED", at, 0.0, 0, True, "FOREX_SESSION_CLOSED")

        current_price = float(price)
        state = self._states.get(key)
        if state is None:
            self._states[key] = _QuoteState(current_price, at, at, 1)
            return self._assessment(
                "INSUFFICIENT_HISTORY",
                at,
                0.0,
                1,
                True,
                "QUOTE_BASELINE_ESTABLISHED",
            )
        if at < state.last_observed_at_utc:
            return self._assessment(
                "OUT_OF_ORDER",
                at,
                max(0.0, (state.last_observed_at_utc - state.last_changed_at_utc).total_seconds()),
                state.consecutive_unchanged,
                True,
                "QUOTE_TIMESTAMP_REGRESSION",
            )

        tolerance = max(abs(state.price), abs(current_price), 1.0) * self.relative_tolerance
        changed = abs(current_price - state.price) > tolerance
        if changed:
            self._states[key] = _QuoteState(current_price, at, at, 1)
            return self._assessment("LIVE", at, 0.0, 1, False, "QUOTE_PRICE_CHANGED")

        consecutive = state.consecutive_unchanged + 1
        unchanged_seconds = max(0.0, (at - state.last_changed_at_utc).total_seconds())
        self._states[key] = _QuoteState(
            current_price,
            at,
            state.last_changed_at_utc,
            consecutive,
        )
        frozen = (
            consecutive >= self.min_unchanged_observations
            and unchanged_seconds >= self.frozen_after_seconds
        )
        if frozen:
            return self._assessment(
                "PRICE_FROZEN",
                at,
                unchanged_seconds,
                consecutive,
                True,
                "LIVE_TICK_VALUE_UNCHANGED_BEYOND_THRESHOLD",
            )
        return self._assessment(
            "INSUFFICIENT_HISTORY",
            at,
            unchanged_seconds,
            consecutive,
            True,
            "UNCHANGED_QUOTE_BELOW_FROZEN_THRESHOLD",
        )

    @staticmethod
    def _assessment(
        status: QuoteHealthStatus,
        at: datetime,
        unchanged_seconds: float,
        consecutive: int,
        blocked: bool,
        reason: str,
    ) -> FrozenQuoteAssessment:
        return FrozenQuoteAssessment(status, at, unchanged_seconds, consecutive, blocked, reason)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("quote observation time requires a UTC offset")
    return value.astimezone(UTC)


__all__ = ["FrozenQuoteAssessment", "FrozenQuoteDetector", "QuoteHealthStatus"]
