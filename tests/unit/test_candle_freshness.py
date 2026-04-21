from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.candle_freshness import candle_age_seconds, parse_candle_timestamp


def test_parse_iso_timestamp():
    parsed = parse_candle_timestamp("2026-04-20T12:30:00+00:00")
    assert parsed == datetime(2026, 4, 20, 12, 30, tzinfo=UTC)


def test_parse_z_timestamp():
    parsed = parse_candle_timestamp("2026-04-20T12:30:00Z")
    assert parsed == datetime(2026, 4, 20, 12, 30, tzinfo=UTC)


def test_parse_epoch_seconds():
    parsed = parse_candle_timestamp(1_745_152_800)
    assert parsed == datetime.fromtimestamp(1_745_152_800, tz=UTC)


def test_parse_epoch_milliseconds():
    parsed = parse_candle_timestamp(1_745_152_800_000)
    assert parsed == datetime.fromtimestamp(1_745_152_800, tz=UTC)


def test_missing_timestamp_returns_none():
    assert parse_candle_timestamp(None) is None


def test_invalid_timestamp_returns_none():
    assert parse_candle_timestamp("not-a-timestamp") is None


def test_candle_age_seconds_clamps_future_to_zero():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
    candle = {"timestamp": (now + timedelta(hours=1)).isoformat()}
    assert candle_age_seconds(candle, now=now) == 0.0


def test_candle_age_seconds_uses_iso_timestamp():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
    candle = {"timestamp": "2026-04-21T09:00:00Z"}
    assert candle_age_seconds(candle, now=now) == 10800.0


def test_candle_age_seconds_returns_none_without_supported_field():
    assert candle_age_seconds({"close": 1.1}) is None
