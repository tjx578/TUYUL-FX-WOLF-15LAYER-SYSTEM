from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_candle_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    if isinstance(value, int | float):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                numeric = float(raw)
            except ValueError:
                return None
            return parse_candle_timestamp(numeric)
        dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    return None


def candle_age_seconds(candle: dict[str, Any], now: datetime | None = None) -> float | None:
    reference_now = now or datetime.now(UTC)
    ts = (
        candle.get("timestamp")
        or candle.get("time")
        or candle.get("datetime")
        or candle.get("open_time")
        or candle.get("close_time")
    )
    parsed = parse_candle_timestamp(ts)
    if parsed is None:
        return None
    return max(0.0, (reference_now - parsed).total_seconds())


__all__ = ["candle_age_seconds", "parse_candle_timestamp"]
