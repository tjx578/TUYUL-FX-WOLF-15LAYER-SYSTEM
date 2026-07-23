"""Canonical, provenance-aware OHLC candle contract.

The contract separates provider timestamp semantics from the canonical window.
Only candles whose closure can be proven may be used as Strategy 5S-CR
evidence.  Ambiguous legacy payloads can still be retained as diagnostics by
marking them incomplete with ``UNSPECIFIED`` timestamp semantics.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CandleTimeframe = Literal["M1", "M5", "M15", "H1", "H4", "D1", "W1", "MN"]
ProviderTimestampSemantics = Literal[
    "PERIOD_OPEN",
    "PERIOD_END",
    "CANONICAL_WINDOW",
    "UNSPECIFIED",
]

TIMEFRAME_DELTAS: dict[str, timedelta] = {
    "M1": timedelta(minutes=1),
    "M5": timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D1": timedelta(days=1),
    "W1": timedelta(days=7),
}


def as_utc(value: datetime, field_name: str) -> datetime:
    """Normalize an offset-aware timestamp to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class CanonicalCandle(BaseModel):
    """One immutable OHLC window with explicit closure and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._:-]+$")
    timeframe: CandleTimeframe
    open_time: datetime
    close_time: datetime
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(default=0.0, ge=0)
    tick_count: int = Field(default=0, ge=0)
    complete: bool
    provider: str = Field(..., min_length=2, max_length=100)
    provider_timestamp_semantics: ProviderTimestampSemantics
    provider_timestamp: datetime | None = None

    @field_validator("open_time", "close_time", "provider_timestamp")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return None if value is None else as_utc(value, str(info.field_name))

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _numbers_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("candle prices and volume must be finite")
        return value

    @model_validator(mode="after")
    def _window_and_ohlc_are_valid(self) -> CanonicalCandle:
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        expected = TIMEFRAME_DELTAS.get(self.timeframe)
        if expected is not None and self.close_time - self.open_time != expected:
            raise ValueError(f"{self.timeframe} candle window must be exactly {expected}")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to all OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to all OHLC values")
        if self.complete and self.provider_timestamp_semantics == "UNSPECIFIED":
            raise ValueError("complete candle cannot use unspecified timestamp semantics")
        return self

    def is_authoritative_closed_as_of(self, as_of_utc: datetime) -> bool:
        """Return whether this candle is legal evidence at ``as_of_utc``."""

        cutoff = as_utc(as_of_utc, "as_of_utc")
        return (
            self.complete
            and self.provider_timestamp_semantics != "UNSPECIFIED"
            and self.close_time <= cutoff
        )


__all__ = [
    "CandleTimeframe",
    "CanonicalCandle",
    "ProviderTimestampSemantics",
    "TIMEFRAME_DELTAS",
    "as_utc",
]
