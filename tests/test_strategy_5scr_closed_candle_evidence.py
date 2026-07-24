from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from analysis.strategy_5scr_closed_candle_provider import (
    FutureCandleLeakageError,
    Strategy5SCRClosedCandleEvidenceProvider,
)
from analysis.strategy_5scr_replay import FrozenClosedCandleStore, Strategy5SCRReplay
from contracts.canonical_candle import TIMEFRAME_DELTAS, CanonicalCandle
from ingest.finnhub_candles import FinnhubCandleFetcher

DECISION_AT = datetime(2026, 7, 20, 6, 51, 26, 930659, tzinfo=UTC)


def _candle(
    timeframe: str,
    close_time: datetime,
    *,
    symbol: str = "NZDUSD",
    open_price: float,
    high: float,
    low: float,
    close: float,
    complete: bool = True,
    provider: str = "finnhub",
) -> CanonicalCandle:
    return CanonicalCandle.model_validate(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": close_time - TIMEFRAME_DELTAS[timeframe],
            "close_time": close_time,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100,
            "tick_count": 10,
            "complete": complete,
            "provider": provider,
            "provider_timestamp_semantics": "CANONICAL_WINDOW",
        }
    )


def _snapshot(
    *,
    symbol: str = "NZDUSD",
    include_future: bool = False,
) -> dict[str, list[CanonicalCandle]]:
    d1 = [
        _candle(
            "D1",
            datetime(2026, 7, 18 + index, tzinfo=UTC),
            symbol=symbol,
            open_price=1.08 + index * 0.005,
            high=1.10 + index * 0.005,
            low=1.07 + index * 0.005,
            close=1.09 + index * 0.005,
        )
        for index in range(2)
    ]
    # The third daily candle closes before the intraday decision.
    d1.append(
        _candle(
            "D1",
            datetime(2026, 7, 20, tzinfo=UTC),
            symbol=symbol,
            open_price=1.09,
            high=1.115,
            low=1.085,
            close=1.105,
        )
    )
    h4_closes = [
        datetime(2026, 7, 19, 16, tzinfo=UTC),
        datetime(2026, 7, 19, 20, tzinfo=UTC),
        datetime(2026, 7, 20, 0, tzinfo=UTC),
        datetime(2026, 7, 20, 4, tzinfo=UTC),
    ]
    h4 = [
        _candle(
            "H4",
            close_at,
            symbol=symbol,
            open_price=1.09 + index * 0.002,
            high=1.11 + index * 0.001,
            low=1.08 + index * 0.002,
            close=1.095 + index * 0.002,
        )
        for index, close_at in enumerate(h4_closes)
    ]
    h1 = [
        _candle(
            "H1",
            datetime(2026, 7, 20, 5, tzinfo=UTC),
            symbol=symbol,
            open_price=1.099,
            high=1.101,
            low=1.098,
            close=1.100,
        ),
        _candle(
            "H1",
            datetime(2026, 7, 20, 6, tzinfo=UTC),
            symbol=symbol,
            open_price=1.100,
            high=1.103,
            low=1.099,
            close=1.102,
        ),
    ]
    m15 = [
        _candle(
            "M15",
            datetime(2026, 7, 20, 6, 15, tzinfo=UTC),
            symbol=symbol,
            open_price=1.0990,
            high=1.1000,
            low=1.0985,
            close=1.0995,
        ),
        _candle(
            "M15",
            datetime(2026, 7, 20, 6, 30, tzinfo=UTC),
            symbol=symbol,
            open_price=1.0995,
            high=1.1010,
            low=1.0990,
            close=1.1005,
        ),
        _candle(
            "M15",
            datetime(2026, 7, 20, 6, 45, tzinfo=UTC),
            symbol=symbol,
            open_price=1.1005,
            high=1.1030,
            low=1.1000,
            close=1.1020,
        ),
    ]
    m1 = [
        _candle(
            "M1",
            datetime(2026, 7, 20, 6, 49 + index, tzinfo=UTC),
            symbol=symbol,
            open_price=1.1010 + index * 0.0003,
            high=1.1020 + index * 0.0003,
            low=1.1005 + index * 0.0003,
            close=1.1014 + index * 0.0003,
            provider="finnhub_ws_tick_builder",
        )
        for index in range(3)
    ]
    if include_future:
        m1.append(
            _candle(
                "M1",
                datetime(2026, 7, 20, 6, 52, tzinfo=UTC),
                symbol=symbol,
                open_price=1.102,
                high=1.103,
                low=1.101,
                close=1.1025,
                provider="finnhub_ws_tick_builder",
            )
        )
    return {"D1": d1, "H4": h4, "H1": h1, "M15": m15, "M1": m1}


@pytest.mark.asyncio
async def test_provider_builds_frozen_asof_shadow_evidence() -> None:
    candles = [candle for batch in _snapshot().values() for candle in batch]
    provider = Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(candles))

    evidence = await provider.provide(symbol="NZDUSD", decision_at_utc=DECISION_AT)

    assert evidence is not None
    assert evidence.evidence_mode == "SHADOW"
    assert evidence.evidence_snapshot_id is not None
    assert evidence.execution_cost_authority == "ESTIMATED_NOT_BROKER"
    assert evidence.source_candle_count == len(candles)
    assert len(evidence.source_candles) == len(candles)
    assert all(candle.provider_timestamp_semantics != "UNSPECIFIED" for candle in evidence.source_candles)
    assert max(evidence.source_candle_close_times) <= DECISION_AT
    assert evidence.h1 is not None and evidence.h1.structure_confirmed is True
    assert evidence.m15 is not None and evidence.m15.structural_break is True


@pytest.mark.asyncio
async def test_ordered_resolver_requires_m15_proof_after_lifecycle_anchor() -> None:
    candles = [candle for batch in _snapshot().values() for candle in batch]
    provider = Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(candles))

    evidence = await provider.provide(
        symbol="NZDUSD",
        decision_at_utc=DECISION_AT,
        lifecycle_anchor_utc=datetime(2026, 7, 20, 6, 31, tzinfo=UTC),
    )

    assert evidence is not None
    assert evidence.lifecycle_anchor_utc == datetime(2026, 7, 20, 6, 31, tzinfo=UTC)
    assert evidence.m15 is not None
    assert evidence.m15.structural_break is True
    assert evidence.m15.acceptance_confirmed is False
    assert evidence.m1 is None


@pytest.mark.asyncio
async def test_ordered_resolver_builds_m1_only_after_m15_acceptance() -> None:
    candles = [candle for batch in _snapshot().values() for candle in batch]
    provider = Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(candles))

    evidence = await provider.provide(
        symbol="NZDUSD",
        decision_at_utc=DECISION_AT,
        lifecycle_anchor_utc=datetime(2026, 7, 20, 6, 0, tzinfo=UTC),
    )

    assert evidence is not None
    assert evidence.m15 is not None and evidence.m15.acceptance_confirmed is True
    assert evidence.m1 is not None and evidence.m1.formed_at_utc is not None
    assert evidence.m1.formed_at_utc > evidence.m15.confirmed_at_utc


@pytest.mark.asyncio
async def test_snapshot_identity_includes_lifecycle_anchor() -> None:
    candles = [candle for batch in _snapshot().values() for candle in batch]
    provider = Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(candles))

    first = await provider.provide(
        symbol="NZDUSD",
        decision_at_utc=DECISION_AT,
        lifecycle_anchor_utc=datetime(2026, 7, 20, 6, 0, tzinfo=UTC),
    )
    second = await provider.provide(
        symbol="NZDUSD",
        decision_at_utc=DECISION_AT,
        lifecycle_anchor_utc=datetime(2026, 7, 20, 6, 1, tzinfo=UTC),
    )

    assert first is not None and second is not None
    assert first.evidence_snapshot_id != second.evidence_snapshot_id


@pytest.mark.parametrize(
    ("symbol", "expected_pip_size"),
    [("CHFJPY", 0.01), ("EURGBP", 0.0001), ("XAUUSD", 0.01)],
)
@pytest.mark.asyncio
async def test_provider_supports_shadow_validation_symbols(
    symbol: str,
    expected_pip_size: float,
) -> None:
    snapshot = _snapshot(symbol=symbol)
    provider = Strategy5SCRClosedCandleEvidenceProvider(
        FrozenClosedCandleStore([candle for batch in snapshot.values() for candle in batch])
    )

    evidence = await provider.provide(symbol=symbol, decision_at_utc=DECISION_AT)

    assert evidence is not None
    assert evidence.pip_size == expected_pip_size
    assert evidence.execution_cost_authority == "ESTIMATED_NOT_BROKER"


def test_direct_snapshot_rejects_future_candle_leakage() -> None:
    provider = Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(()))

    with pytest.raises(FutureCandleLeakageError):
        provider.build_from_snapshot(
            symbol="NZDUSD",
            decision_at_utc=DECISION_AT,
            candles_by_timeframe=_snapshot(include_future=True),
        )


@pytest.mark.asyncio
async def test_replay_keeps_post_decision_outcome_out_of_evidence() -> None:
    snapshot = _snapshot()
    future = _candle(
        "M1",
        # The 06:51 candle straddles the 06:51:26 decision and is not a legal
        # post-decision outcome bar.  Start with the next complete M1 window.
        datetime(2026, 7, 20, 6, 53, tzinfo=UTC),
        open_price=1.102,
        high=1.103,
        low=1.101,
        close=1.1025,
        provider="finnhub_ws_tick_builder",
    )
    replay = Strategy5SCRReplay([candle for batch in snapshot.values() for candle in batch] + [future])

    evidence = await replay.build_evidence(symbol="NZDUSD", decision_at_utc=DECISION_AT)
    outcomes = replay.load_outcome_candles(
        symbol="NZDUSD",
        timeframe="M1",
        decision_at_utc=DECISION_AT,
    )

    assert evidence is not None
    assert future.close_time not in evidence.source_candle_close_times
    assert outcomes == (future,)


def _h1_payload(close_hour: int, *, complete: bool = True) -> dict[str, Any]:
    close_time = datetime(2026, 7, 20, close_hour, tzinfo=UTC)
    return {
        "symbol": "NZDUSD",
        "timeframe": "H1",
        "open_time": close_time - timedelta(hours=1),
        "close_time": close_time,
        "timestamp": close_time,
        "open": 1.10,
        "high": 1.11,
        "low": 1.09,
        "close": 1.105,
        "volume": 10,
        "complete": complete,
        "provider": "finnhub",
        "provider_timestamp_semantics": "PERIOD_END",
        "source": "rest_api",
    }


def test_h4_is_authoritative_only_for_four_complete_contiguous_h1() -> None:
    fetcher = FinnhubCandleFetcher()

    complete = fetcher.aggregate_h4([_h1_payload(hour) for hour in (1, 2, 3, 4)])
    partial = fetcher.aggregate_h4([_h1_payload(hour) for hour in (1, 2, 3)])
    gapped = fetcher.aggregate_h4([_h1_payload(hour) for hour in (1, 2, 4)])

    assert len(complete) == 1 and complete[0]["complete"] is True
    assert complete[0]["aggregation_component_count"] == 4
    assert len(partial) == 1 and partial[0]["complete"] is False
    assert len(gapped) == 1 and gapped[0]["complete"] is False


def test_finnhub_normalization_marks_forming_candle_incomplete() -> None:
    forming_open = datetime(2026, 7, 20, 6, tzinfo=UTC)
    cutoff = forming_open + timedelta(minutes=30)
    forming_close = forming_open + timedelta(hours=1)
    response = {
        "s": "ok",
        "o": [1.10],
        "h": [1.11],
        "l": [1.09],
        "c": [1.105],
        "v": [100],
        "t": [int(forming_open.timestamp())],
    }

    candle = FinnhubCandleFetcher().normalize_response(
        response,
        "NZDUSD",
        "H1",
        as_of_utc=cutoff,
    )[0]

    assert candle["open_time"] == forming_open
    assert candle["close_time"] == forming_close
    assert candle["complete"] is False
    assert candle["provider_timestamp_semantics"] == "PERIOD_OPEN"


def test_finnhub_refresh_promotes_the_same_period_from_forming_to_closed() -> None:
    open_time = datetime(2026, 7, 20, 6, tzinfo=UTC)
    close_time = open_time + timedelta(hours=1)
    response = {
        "s": "ok",
        "o": [1.10],
        "h": [1.11],
        "l": [1.09],
        "c": [1.105],
        "v": [100],
        "t": [int(open_time.timestamp())],
    }
    fetcher = FinnhubCandleFetcher()

    forming = fetcher.normalize_response(
        response,
        "NZDUSD",
        "H1",
        as_of_utc=open_time + timedelta(minutes=30),
    )[0]
    closed = fetcher.normalize_response(
        response,
        "NZDUSD",
        "H1",
        as_of_utc=close_time,
    )[0]

    assert forming["open_time"] == closed["open_time"] == open_time
    assert forming["close_time"] == closed["close_time"] == close_time
    assert forming["complete"] is False
    assert closed["complete"] is True


@pytest.mark.asyncio
async def test_fetch_range_uses_historical_cutoff_and_returns_canonical_window() -> None:
    start = datetime(2026, 7, 20, 5, tzinfo=UTC)
    end = datetime(2026, 7, 20, 6, tzinfo=UTC)
    requested: dict[str, Any] = {}

    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "s": "ok",
                "o": [1.10],
                "h": [1.11],
                "l": [1.09],
                "c": [1.105],
                "v": [100],
                "t": [int(start.timestamp())],
            }

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any]) -> _Response:
            requested.update(params)
            return _Response()

    fetcher = FinnhubCandleFetcher()
    fetcher.request_delay = 0
    fetcher._key_manager = MagicMock()
    fetcher._key_manager.current_key.return_value = "test-key"

    with patch("ingest.finnhub_candles.httpx.AsyncClient", return_value=_Client()):
        candles = await fetcher.fetch_range("NZDUSD", "H1", start, end)

    assert requested["from"] == int(start.timestamp())
    assert requested["to"] == int(end.timestamp())
    assert len(candles) == 1
    assert candles[0]["open_time"] == start
    assert candles[0]["close_time"] == end
    assert candles[0]["complete"] is True
    assert candles[0]["provider_timestamp_semantics"] == "PERIOD_OPEN"
