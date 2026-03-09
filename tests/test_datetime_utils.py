from datetime import UTC, datetime

from news.datetime_utils import (
    parse_finnhub_datetime,
    parse_forexfactory_datetime,
    parse_forexfactory_event_time,
    to_iso_utc,
)


def test_parse_forexfactory_datetime_is_utc() -> None:
    dt = parse_forexfactory_datetime("2026-01-15", "8:30am")
    assert dt.tzinfo == UTC


def test_parse_forexfactory_event_time_timeless_returns_none() -> None:
    assert parse_forexfactory_event_time("2026-03-08", "All Day") is None


def test_parse_finnhub_datetime_iso() -> None:
    dt = parse_finnhub_datetime("2026-03-08T12:30:00Z")
    assert dt.tzinfo == UTC
    assert dt.hour == 12


def test_parse_finnhub_datetime_unix() -> None:
    dt = parse_finnhub_datetime(1741435800)
    assert dt.tzinfo == UTC


def test_to_iso_utc_handles_naive_and_aware() -> None:
    aware = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 3, 8, 12, 0)
    assert to_iso_utc(aware) == "2026-03-08T12:00:00+00:00"
    assert to_iso_utc(naive) == "2026-03-08T12:00:00+00:00"
