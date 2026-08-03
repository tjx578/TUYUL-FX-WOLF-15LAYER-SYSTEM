"""Stateful, session-aware detection for live quotes whose value stops moving."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from utils.market_hours import is_forex_market_open

QuoteHealthStatus = Literal[
    "LIVE",
    "PRICE_QUALITY_WARMING_UP",
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
    observation_count: int
    warmup_elapsed_seconds: float
    execution_blocked: bool
    reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "quote_health_status": self.status,
            "quote_health_observed_at_utc": self.observed_at_utc.isoformat(),
            "quote_unchanged_seconds": round(self.unchanged_seconds, 3),
            "quote_consecutive_unchanged": self.consecutive_unchanged,
            "quote_observation_count": self.observation_count,
            "quote_warmup_elapsed_seconds": round(self.warmup_elapsed_seconds, 3),
            "quote_health_execution_blocked": self.execution_blocked,
            "quote_health_reason": self.reason,
            "quote_health_rule_version": "frozen-quote.v2-restart-warmup",
        }


@dataclass(slots=True)
class _QuoteState:
    price: float
    first_observed_at_utc: datetime
    last_observed_at_utc: datetime
    last_changed_at_utc: datetime
    consecutive_unchanged: int
    observation_count: int


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
        warmup_seconds: float = 30.0,
        min_warmup_observations: int = 3,
        relative_tolerance: float = 1e-9,
    ) -> None:
        if frozen_after_seconds <= 0:
            raise ValueError("frozen_after_seconds must be positive")
        if min_unchanged_observations < 2:
            raise ValueError("min_unchanged_observations must be at least 2")
        if warmup_seconds < 0:
            raise ValueError("warmup_seconds cannot be negative")
        if min_warmup_observations < 2:
            raise ValueError("min_warmup_observations must be at least 2")
        if relative_tolerance < 0:
            raise ValueError("relative_tolerance cannot be negative")
        self.frozen_after_seconds = float(frozen_after_seconds)
        self.min_unchanged_observations = int(min_unchanged_observations)
        self.warmup_seconds = float(warmup_seconds)
        self.min_warmup_observations = int(min_warmup_observations)
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
            self._states[key] = _QuoteState(current_price, at, at, at, 1, 1)
            return self._assessment(
                "PRICE_QUALITY_WARMING_UP",
                at,
                0.0,
                1,
                True,
                "QUOTE_RESTART_WARMUP_BASELINE_ESTABLISHED",
                observation_count=1,
                warmup_elapsed_seconds=0.0,
            )
        if at < state.last_observed_at_utc:
            return self._assessment(
                "OUT_OF_ORDER",
                at,
                max(0.0, (state.last_observed_at_utc - state.last_changed_at_utc).total_seconds()),
                state.consecutive_unchanged,
                True,
                "QUOTE_TIMESTAMP_REGRESSION",
                observation_count=state.observation_count,
                warmup_elapsed_seconds=max(
                    0.0,
                    (state.last_observed_at_utc - state.first_observed_at_utc).total_seconds(),
                ),
            )

        tolerance = max(abs(state.price), abs(current_price), 1.0) * self.relative_tolerance
        changed = abs(current_price - state.price) > tolerance
        observation_count = state.observation_count + 1
        warmup_elapsed = max(0.0, (at - state.first_observed_at_utc).total_seconds())
        if changed:
            next_state = _QuoteState(
                current_price,
                state.first_observed_at_utc,
                at,
                at,
                1,
                observation_count,
            )
            self._states[key] = next_state
            if not self._warmup_complete(next_state, at):
                return self._assessment(
                    "PRICE_QUALITY_WARMING_UP",
                    at,
                    0.0,
                    1,
                    True,
                    "QUOTE_RESTART_WARMUP_INCOMPLETE",
                    observation_count=observation_count,
                    warmup_elapsed_seconds=warmup_elapsed,
                )
            return self._assessment(
                "LIVE",
                at,
                0.0,
                1,
                False,
                "QUOTE_PRICE_CHANGED",
                observation_count=observation_count,
                warmup_elapsed_seconds=warmup_elapsed,
            )

        consecutive = state.consecutive_unchanged + 1
        unchanged_seconds = max(0.0, (at - state.last_changed_at_utc).total_seconds())
        self._states[key] = _QuoteState(
            current_price,
            state.first_observed_at_utc,
            at,
            state.last_changed_at_utc,
            consecutive,
            observation_count,
        )
        frozen = consecutive >= self.min_unchanged_observations and unchanged_seconds >= self.frozen_after_seconds
        if frozen:
            return self._assessment(
                "PRICE_FROZEN",
                at,
                unchanged_seconds,
                consecutive,
                True,
                "LIVE_TICK_VALUE_UNCHANGED_BEYOND_THRESHOLD",
                observation_count=observation_count,
                warmup_elapsed_seconds=warmup_elapsed,
            )
        warming_up = not self._warmup_complete(self._states[key], at)
        return self._assessment(
            "PRICE_QUALITY_WARMING_UP" if warming_up else "INSUFFICIENT_HISTORY",
            at,
            unchanged_seconds,
            consecutive,
            True,
            "QUOTE_RESTART_WARMUP_INCOMPLETE" if warming_up else "UNCHANGED_QUOTE_BELOW_FROZEN_THRESHOLD",
            observation_count=observation_count,
            warmup_elapsed_seconds=warmup_elapsed,
        )

    def _warmup_complete(self, state: _QuoteState, at: datetime) -> bool:
        return (
            state.observation_count >= self.min_warmup_observations
            and (at - state.first_observed_at_utc).total_seconds() >= self.warmup_seconds
        )

    @staticmethod
    def _assessment(
        status: QuoteHealthStatus,
        at: datetime,
        unchanged_seconds: float,
        consecutive: int,
        blocked: bool,
        reason: str,
        *,
        observation_count: int = 0,
        warmup_elapsed_seconds: float = 0.0,
    ) -> FrozenQuoteAssessment:
        return FrozenQuoteAssessment(
            status,
            at,
            unchanged_seconds,
            consecutive,
            observation_count,
            warmup_elapsed_seconds,
            blocked,
            reason,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("quote observation time requires a UTC offset")
    return value.astimezone(UTC)


__all__ = ["FrozenQuoteAssessment", "FrozenQuoteDetector", "QuoteHealthStatus"]
