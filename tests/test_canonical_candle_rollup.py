from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingest.candle_builder import Candle
from ingest.canonical_rollup import aggregate_contiguous_candles


def _candle(
    timeframe: str,
    open_time: datetime,
    *,
    complete: bool = True,
    provider: str = "finnhub",
) -> Candle:
    minutes = {"M15": 15, "H1": 60}[timeframe]
    offset = (open_time.hour * 60 + open_time.minute) / 100_000
    return Candle(
        symbol="EURUSD",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=minutes),
        open=1.1000 + offset,
        high=1.1020 + offset,
        low=1.0990 + offset,
        close=1.1010 + offset,
        volume=10.0,
        tick_count=5,
        complete=complete,
        provider=provider,
        provider_timestamp_semantics="PERIOD_OPEN",
        provider_timestamp=open_time,
        provider_feed="oanda_rest",
    )


def test_four_contiguous_m15_create_one_complete_h1() -> None:
    start = datetime(2026, 7, 20, 8, tzinfo=UTC)
    source = [_candle("M15", start + index * timedelta(minutes=15)) for index in range(4)]

    result = aggregate_contiguous_candles(
        source,
        source_timeframe="M15",
        target_timeframe="H1",
    )

    assert len(result) == 1
    h1 = result[0]
    assert h1.timeframe == "H1"
    assert h1.open_time == start
    assert h1.close_time == start + timedelta(hours=1)
    assert h1.complete is True
    assert h1.provider_timestamp_semantics == "CANONICAL_WINDOW"
    assert h1.provider_feed.startswith("canonical_rollup:M15-H1:")


def test_gapped_or_forming_m15_cannot_create_h1() -> None:
    start = datetime(2026, 7, 20, 8, tzinfo=UTC)
    gapped = [_candle("M15", start + index * timedelta(minutes=15)) for index in (0, 1, 3)]
    forming = [_candle("M15", start + index * timedelta(minutes=15)) for index in range(4)]
    forming[-1].complete = False

    assert (
        aggregate_contiguous_candles(
            gapped,
            source_timeframe="M15",
            target_timeframe="H1",
        )
        == []
    )
    assert (
        aggregate_contiguous_candles(
            forming,
            source_timeframe="M15",
            target_timeframe="H1",
        )
        == []
    )


def test_four_contiguous_h1_create_one_complete_h4() -> None:
    start = datetime(2026, 7, 20, 8, tzinfo=UTC)
    source = [_candle("H1", start + index * timedelta(hours=1)) for index in range(4)]

    result = aggregate_contiguous_candles(
        source,
        source_timeframe="H1",
        target_timeframe="H4",
    )

    assert len(result) == 1
    h4 = result[0]
    assert h4.timeframe == "H4"
    assert h4.open_time == start
    assert h4.close_time == start + timedelta(hours=4)
    assert h4.complete is True
