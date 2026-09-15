"""Offline contracts for batch warmup reporting, including source failures."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import orjson
import pytest
import redis

from api import redis_context_reader as context_reader
from context.candle_history_acceptance import collapse_stale_ohlc, decode_candle_history
from context.warmup_requirements import WARMUP_MIN_BARS
from core.redis_keys import CANDLE_HISTORY_MAXLEN


def _bars(count: int) -> list[bytes]:
    return [orjson.dumps({"open": i, "high": i + 1, "low": i - 1, "close": i}) for i in range(count)]


def _histories(counts: list[object]) -> list[object]:
    return [_bars(value) if type(value) is int and value >= 0 else value for value in counts]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setenv("CANDLE_HISTORY_KEY_PREFIXES", "wolf15:candle_history")
    fake = MagicMock()
    fake.pipeline.return_value.__enter__.return_value = fake.pipeline.return_value
    monkeypatch.setattr(context_reader, "_context_redis_client", lambda: fake)
    monkeypatch.setattr(context_reader, "_REDIS_UNAVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(context_reader, "_REDIS_FAILURE_COUNT", 0)
    monkeypatch.setenv("API_CONTEXT_REDIS_FAILURE_COOLDOWN_SEC", "10")
    return fake


def test_batch_counts_preserve_symbol_order_and_use_one_round_trip(client: MagicMock) -> None:
    pipe = client.pipeline.return_value
    pipe.execute.return_value = _histories([30, 10, 5, 5, 2, 29, 10, 5, 5, 2])
    result = context_reader.RedisContextReader().check_warmup_many(["EURUSD", "GBPUSD", "EURUSD"])
    assert list(result) == ["EURUSD", "GBPUSD"]
    assert result["EURUSD"]["ready"] is True
    assert result["GBPUSD"]["ready"] is False
    assert result["GBPUSD"]["missing"] == {"H1": 1}
    assert result["GBPUSD"]["details"]["H1"] == {"have": 29, "need": 30, "missing": 1}
    assert result["EURUSD"]["required"] == WARMUP_MIN_BARS
    assert WARMUP_MIN_BARS["H1"] == 30
    client.pipeline.assert_called_once_with(transaction=False)
    pipe.execute.assert_called_once_with(raise_on_error=False)
    assert pipe.lrange.call_args_list == [
        call(f"wolf15:candle_history:{symbol}:{tf}", 0, CANDLE_HISTORY_MAXLEN)
        for symbol in ["EURUSD", "GBPUSD"]
        for tf in WARMUP_MIN_BARS
    ]
    client.ping.assert_not_called()
    client.llen.assert_not_called()


def test_custom_requirements_and_single_symbol_parity(client: MagicMock) -> None:
    pipe = client.pipeline.return_value
    pipe.execute.side_effect = [_histories([3, 1]), _histories([3]), _histories([1])]
    reader = context_reader.RedisContextReader()
    requirements = {"M5": 2, "H1": 4}
    assert reader.check_warmup_many(["EURUSD"], requirements)["EURUSD"] == reader.check_warmup("EURUSD", requirements)


def test_empty_batch_avoids_redis(client: MagicMock) -> None:
    assert context_reader.RedisContextReader().check_warmup_many([]) == {}
    client.pipeline.assert_not_called()


@pytest.mark.parametrize("failure", [redis.ConnectionError("offline"), redis.TimeoutError("timeout")])
def test_batch_failure_is_unready_and_enters_cooldown(client: MagicMock, failure: Exception) -> None:
    client.pipeline.return_value.execute.side_effect = failure
    reader = context_reader.RedisContextReader()
    result = reader.check_warmup_many(["EURUSD", "GBPUSD"], {"H1": 0})
    assert all(item["ready"] is False for item in result.values())
    assert all(item["bars"] == {"H1": 0} for item in result.values())
    assert reader.read_source_ok is False
    assert reader.read_failure_count == 1
    assert reader.check_warmup_many(["EURUSD"])["EURUSD"]["ready"] is False
    client.pipeline.assert_called_once_with(transaction=False)
    assert reader.read_failure_count == 1
    client.llen.assert_not_called()
    client.ping.assert_not_called()


@pytest.mark.parametrize("counts", [[], [30, 10], [-1], [True], ["30"], [redis.ResponseError("wrong type")]])
def test_invalid_batch_cannot_report_ready(client: MagicMock, counts: list[object]) -> None:
    client.pipeline.return_value.execute.return_value = counts
    reader = context_reader.RedisContextReader()
    assert reader.check_warmup_many(["EURUSD"], {"H1": 1})["EURUSD"]["ready"] is False
    assert reader.read_failure_count == 1
    assert reader.read_source_ok is False


def test_successful_read_after_cooldown_recovers_source(client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = context_reader.RedisContextReader()
    client.pipeline.return_value.execute.side_effect = redis.ConnectionError("offline")
    assert reader.check_warmup_many(["EURUSD"])["EURUSD"]["ready"] is False
    monkeypatch.setattr(context_reader, "_REDIS_UNAVAILABLE_UNTIL", 0.0)
    client.pipeline.return_value.execute.side_effect = None
    client.pipeline.return_value.execute.return_value = _histories([30, 10, 5, 5, 2])
    assert reader.check_warmup_many(["EURUSD"])["EURUSD"]["ready"] is True
    assert reader.read_source_ok is True
    assert reader.read_failure_count == 1


def test_single_symbol_uses_canonical_h1_threshold(client: MagicMock) -> None:
    client.pipeline.return_value.execute.side_effect = [_histories([n]) for n in [29, 10, 5, 5, 2]]
    result = context_reader.RedisContextReader().check_warmup("EURUSD")
    assert result["ready"] is False
    assert result["missing"] == {"H1": 1}
    assert result["required"] == WARMUP_MIN_BARS


@pytest.mark.parametrize(
    ("prefixes", "counts", "expected"),
    [
        (None, [0, 30], 30),
        (None, [12, 30], 12),
        ("custom:candles, candle_history", [31, 99], 31),
        ("custom:candles, candle_history", [0, 32], 32),
        (" , , ", [0, 33], 33),
        (None, [redis.ResponseError("WRONGTYPE Operation against a key"), 30], 30),
        (None, [30, redis.ResponseError("WRONGTYPE Operation against a key")], 30),
        (None, [0, 0], 0),
    ],
)
def test_prefix_precedence_for_single_and_batch(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch, prefixes: str | None, counts: list[object], expected: int
) -> None:
    if prefixes is None:
        monkeypatch.delenv("CANDLE_HISTORY_KEY_PREFIXES")
    else:
        monkeypatch.setenv("CANDLE_HISTORY_KEY_PREFIXES", prefixes)
    client.pipeline.return_value.execute.return_value = _histories(counts)
    reader = context_reader.RedisContextReader()
    batch = reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]
    assert batch["bars"] == {"H1": expected}
    assert batch["ready"] is (expected >= 30)
    assert batch == reader.check_warmup("EURUSD", {"H1": 30})
    assert reader.read_source_ok is True
    assert reader.read_failure_count == 0
    assert client.pipeline.return_value.execute.call_count == 2
    client.llen.assert_not_called()


def test_prefix_selection_is_per_timeframe_without_sum_or_max(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CANDLE_HISTORY_KEY_PREFIXES")
    pipe = client.pipeline.return_value
    pipe.execute.return_value = _histories([12, 30, 0, 10, 0, 31, 4, 10])
    result = context_reader.RedisContextReader().check_warmup_many(["EURUSD", "GBPUSD"], {"H1": 30, "H4": 10})
    assert result["EURUSD"]["bars"] == {"H1": 12, "H4": 10}
    assert result["GBPUSD"]["bars"] == {"H1": 31, "H4": 4}
    assert all(not value["ready"] for value in result.values())
    pipe.execute.assert_called_once_with(raise_on_error=False)
    assert pipe.lrange.call_args_list == [
        call(f"{prefix}:{symbol}:{tf}", 0, CANDLE_HISTORY_MAXLEN)
        for symbol in ["EURUSD", "GBPUSD"]
        for tf in ["H1", "H4"]
        for prefix in ["wolf15:candle_history", "candle_history"]
    ]


def test_non_wrongtype_error_does_not_fall_back_to_ready(client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CANDLE_HISTORY_KEY_PREFIXES")
    client.pipeline.return_value.execute.return_value = [redis.ResponseError("NOPERM denied"), _bars(30)]
    reader = context_reader.RedisContextReader()
    assert reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]["ready"] is False
    assert reader.read_source_ok is False
    assert reader.read_failure_count == 1


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([b"invalid json"] * 30, 0),
        ([b"[]", b"null", b"5"] * 10, 0),
        ([_bars(1)[0]] * 30, 2),
        (_bars(30), 30),
        (_bars(300), 300),
        ([b"bad"] + _bars(29), 29),
    ],
)
def test_counts_follow_shared_consumer_acceptance(client: MagicMock, entries: list[bytes], expected: int) -> None:
    client.pipeline.return_value.execute.return_value = [entries]
    reader = context_reader.RedisContextReader()
    result = reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]
    accepted, _, _ = decode_candle_history(entries)
    assert result["bars"]["H1"] == len(collapse_stale_ohlc(accepted)) == expected
    assert result["ready"] is (expected >= 30)
    assert reader.read_source_ok is True


def test_selected_malformed_prefix_never_falls_back(client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CANDLE_HISTORY_KEY_PREFIXES")
    client.pipeline.return_value.execute.return_value = [[b"bad"] * 30, _bars(30)]
    reader = context_reader.RedisContextReader()
    result = reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]
    assert result["bars"] == {"H1": 0}
    assert result["ready"] is False
    assert reader.read_source_ok is True


def test_selected_over_retention_is_unavailable(client: MagicMock) -> None:
    client.pipeline.return_value.execute.return_value = [_bars(CANDLE_HISTORY_MAXLEN + 1)]
    reader = context_reader.RedisContextReader()
    result = reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]
    assert result["ready"] is False
    assert result["bars"] == {"H1": 0}
    assert reader.read_source_ok is False
    assert reader.read_failure_count == 1
    client.pipeline.return_value.lrange.assert_called_once_with(
        "wolf15:candle_history:EURUSD:H1", 0, CANDLE_HISTORY_MAXLEN
    )


def test_unused_over_retention_does_not_invalidate_selected_prefix(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CANDLE_HISTORY_KEY_PREFIXES")
    client.pipeline.return_value.execute.return_value = [_bars(30), _bars(CANDLE_HISTORY_MAXLEN + 1)]
    reader = context_reader.RedisContextReader()
    assert reader.check_warmup_many(["EURUSD"], {"H1": 30})["EURUSD"]["ready"] is True
    assert reader.read_source_ok is True


@pytest.mark.parametrize("entries", [[b"bad"] * 30, [_bars(1)[0]] * 30, _bars(30), _bars(300)])
def test_reader_counts_match_actual_consumer_load(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch, entries: list[bytes]
) -> None:
    from context.live_context_bus import LiveContextBus
    from context.redis_consumer import RedisConsumer

    bus = LiveContextBus()
    monkeypatch.setattr(bus, "_candle_history", {})
    bus.set_candle_history("BATCH_ACCEPTANCE_TEST", "H1", [])
    consumer = RedisConsumer(["BATCH_ACCEPTANCE_TEST"], MagicMock(), bus)
    monkeypatch.setattr(consumer, "_has_any_candle_seed", AsyncMock(return_value=True))
    monkeypatch.setattr(consumer, "_warmup_candle_history_limited", AsyncMock(return_value=entries))
    monkeypatch.setattr(consumer, "_hydrate_feed_timestamps", AsyncMock())
    asyncio.run(consumer.load_candle_history())
    client.pipeline.return_value.execute.return_value = [entries]
    reader_result = context_reader.RedisContextReader().check_warmup_many(["BATCH_ACCEPTANCE_TEST"], {"H1": 30})
    assert reader_result["BATCH_ACCEPTANCE_TEST"] == bus.check_warmup("BATCH_ACCEPTANCE_TEST", {"H1": 30})
