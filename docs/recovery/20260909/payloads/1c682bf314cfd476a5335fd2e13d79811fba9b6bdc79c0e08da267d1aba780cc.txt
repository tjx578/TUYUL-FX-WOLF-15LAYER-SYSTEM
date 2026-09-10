"""Closed H1 comparability and non-actionable missing evidence."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from context.live_context_bus import LiveContextBus
from context.price_drift import compare_closed_h1

NOW = datetime(2026, 9, 7, 12, 5, tzinfo=UTC)


def bar(ws=False, **changes):
    result = dict(
        symbol="EURUSD",
        timeframe="H1",
        close=1.1,
        complete=True,
        open_time=NOW.replace(hour=11, minute=0),
        close_time=NOW.replace(minute=0),
        received_at_utc=NOW - timedelta(minutes=1),
        source="websocket" if ws else "rest_api",
        provider="wolf15_tick_builder" if ws else "finnhub",
        provider_feed="finnhub_ws" if ws else "finnhub_rest",
        provider_symbol="OANDA:EUR_USD",
    )
    result.update(changes)
    return result


def compare(candles):
    return compare_closed_h1("EURUSD", candles, None, 50, now=NOW.timestamp())


@pytest.mark.parametrize("delta,drifted", [(0, False), (0.0005, False), (0.0075, True)])
def test_aligned(delta, drifted):
    result = compare([bar(), bar(True, close=1.1 + delta)])
    assert result["comparable"] is True
    assert result["drifted"] is drifted
    assert result["drift_pips"] == pytest.approx(delta * 10000)


@pytest.mark.parametrize("lane", [0, 1])
@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "GBPUSD"},
        {"timeframe": "M15"},
        {"complete": False},
        {"complete": "true"},
        {"provider_symbol": None},
        {"provider_symbol": "USDJPY"},
        {"open_time": None},
        {"close_time": None},
        {"received_at_utc": None},
        {"received_at_utc": NOW.replace(tzinfo=None)},
        {"received_at_utc": NOW + timedelta(seconds=1)},
        {"received_at_utc": NOW - timedelta(hours=1)},
        {"open_time": NOW - timedelta(minutes=30)},
        {"close": float("nan")},
        {"close": float("inf")},
        {"close": "invalid"},
        {"close": 0},
        {"provider": None},
    ],
)
def test_invalid_evidence_is_non_actionable(lane, changes):
    candles = [bar(), bar(True)]
    candles[lane].update(changes)
    with patch("context.price_drift.logger") as log:
        result = compare(candles)
    assert result["comparable"] is False
    assert result["actionable"] is False
    assert result["drifted"] is False
    assert result["drift_pips"] == 0
    log.warning.assert_not_called()


@pytest.mark.parametrize("candles", [[], [bar()], [bar(True)], [bar(), bar(True), bar(True)]])
def test_missing_or_ambiguous_evidence(candles):
    assert compare(candles)["comparable"] is False


def test_matching_but_stale_pair():
    candles = [bar(), bar(True, close=1.2)]
    for candle in candles:
        for key in ("open_time", "close_time", "received_at_utc"):
            candle[key] -= timedelta(hours=2)
    result = compare(candles)
    assert result["reason"] == "REST_STALE_CLOSED_H1"
    assert result["drifted"] is False


def test_newer_rest_does_not_fall_back_to_old_matching_pair():
    assert compare([bar(), bar(True), bar(close_time=NOW + timedelta(minutes=55))])["comparable"] is False


def test_ws_requires_actual_lineage():
    assert compare([bar(), bar(True, provider_feed=None)])["reason"] == "WS_LINEAGE_MISSING_OR_INVALID"


def test_other_closed_period_is_not_comparable():
    ws = bar(True, open_time=NOW.replace(hour=10, minute=0), close_time=NOW.replace(hour=11, minute=0))
    assert compare([bar(), ws])["comparable"] is False


@pytest.mark.parametrize("representation", ["iso", "epoch"])
def test_explicit_utc_timestamp_representations(representation):
    candles = [bar(), bar(True)]
    for candle in candles:
        for key in ("open_time", "close_time", "received_at_utc"):
            value = candle[key]
            candle[key] = value.isoformat() if representation == "iso" else value.timestamp()
    assert compare(candles)["comparable"] is True


@pytest.mark.parametrize("threshold", [-1, float("nan"), float("inf")])
def test_invalid_threshold_is_not_actionable(threshold):
    result = compare_closed_h1("EURUSD", [bar(), bar(True)], None, threshold, now=NOW.timestamp())
    assert result["reason"] == "INVALID_DRIFT_THRESHOLD"
    assert result["comparable"] is False


@pytest.mark.parametrize("symbol,delta,expected", [("USDJPY", 0.3, 30), ("XAUUSD", 2, 20)])
def test_instrument_pip_multiplier(symbol, delta, expected):
    candles = [
        bar(symbol=symbol, provider_symbol=symbol),
        bar(True, symbol=symbol, provider_symbol=symbol, close=1.1 + delta),
    ]
    result = compare_closed_h1(symbol, candles, None, 50, now=NOW.timestamp())
    assert result["comparable"] is True
    assert result["drift_pips"] == pytest.approx(expected)


def test_live_gap_is_not_provider_drift():
    result = compare_closed_h1(
        "XAUUSD",
        [bar(symbol="XAUUSD", provider_symbol="OANDA:XAU_USD", close=2500)],
        {"bid": 2509.14, "ask": 2509.16},
        50,
        now=NOW.timestamp(),
    )
    assert result["observed_live_gap_pips"] == pytest.approx(91.5)
    assert result["comparable"] is False
    assert result["drifted"] is False


def test_warning_is_rendered_not_percent_placeholders():
    messages = []
    sink = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    try:
        compare([bar(), bar(True, close=1.1075)])
    finally:
        logger.remove(sink)
    assert len(messages) == 1
    assert "EURUSD REST_close=1.10000 WS_H1_close=1.10750 drift=75.0" in messages[0]
    assert "%s" not in messages[0]


@pytest.mark.parametrize("adapter", ["bus", "redis"])
@pytest.mark.parametrize("aligned", [False, True])
def test_adapters_compare_only_closed_pair(adapter, aligned):
    if adapter == "bus":
        reader = LiveContextBus()
    else:
        from api.redis_context_reader import RedisContextReader

        reader = RedisContextReader()
    current = datetime.now(UTC)
    closed = current.replace(minute=0, second=0, microsecond=0)
    candles = [bar(), bar(True)] if aligned else [bar()]
    for candle in candles:
        candle.update(open_time=closed - timedelta(hours=1), close_time=closed, received_at_utc=current)
    with (
        patch.object(reader, "get_candles", return_value=candles),
        patch.object(reader, "get_latest_tick", return_value={"bid": 2, "ask": 2}),
    ):
        result = reader.check_price_drift("EURUSD", 50)
    assert result["comparable"] is aligned
    assert result["drifted"] is False


@pytest.mark.parametrize("lane,changes", [(0, {"provider_feed": "finnhub_ws"}), (1, {"source": "rest_api"})])
def test_contradictory_lineage_is_rejected(lane, changes):
    candles = [bar(), bar(True)]
    candles[lane].update(changes)
    assert compare(candles)["comparable"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("comparable", [False, None])
async def test_scheduler_does_not_degrade_or_recover_without_comparability(comparable):
    from ingest.h1_refresh_scheduler import H1RefreshScheduler

    with (
        patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher"),
        patch("ingest.h1_refresh_scheduler.SystemStateManager"),
        patch("ingest.h1_refresh_scheduler.load_finnhub", return_value={}),
    ):
        scheduler = H1RefreshScheduler()
    scheduler.fetcher.fetch = AsyncMock(return_value=[bar()])
    scheduler._repair_provider = MagicMock()
    scheduler._repair_provider.fetch = AsyncMock(return_value=MagicMock(candles=[bar()]))
    scheduler.fetcher.aggregate_h4.return_value = []
    scheduler._push_candles_to_redis = AsyncMock()
    scheduler.context_bus = MagicMock()
    scheduler.context_bus.check_price_drift.return_value = {"comparable": comparable, "drifted": True}
    await scheduler._refresh_symbol("EURUSD")
    scheduler.system_state.mark_symbol_degraded.assert_not_called()
    scheduler.system_state.mark_symbol_recovered.assert_not_called()
    scheduler.context_bus.check_price_drift.assert_called_once()
