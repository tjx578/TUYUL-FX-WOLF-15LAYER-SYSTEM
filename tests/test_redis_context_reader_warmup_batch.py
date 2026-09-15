"""Offline contracts for batch warmup reporting, including source failures."""

from unittest.mock import MagicMock, call

import pytest
import redis

from api import redis_context_reader as context_reader
from context.warmup_requirements import WARMUP_MIN_BARS


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = MagicMock()
    fake.pipeline.return_value.__enter__.return_value = fake.pipeline.return_value
    monkeypatch.setattr(context_reader, "_context_redis_client", lambda: fake)
    monkeypatch.setattr(context_reader, "_REDIS_UNAVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(context_reader, "_REDIS_FAILURE_COUNT", 0)
    monkeypatch.setenv("API_CONTEXT_REDIS_FAILURE_COOLDOWN_SEC", "10")
    return fake


def test_batch_counts_preserve_symbol_order_and_use_one_round_trip(client: MagicMock) -> None:
    pipe = client.pipeline.return_value
    pipe.execute.return_value = [30, 10, 5, 5, 2, 29, 10, 5, 5, 2]
    result = context_reader.RedisContextReader().check_warmup_many(["EURUSD", "GBPUSD", "EURUSD"])
    assert list(result) == ["EURUSD", "GBPUSD"]
    assert result["EURUSD"]["ready"] is True
    assert result["GBPUSD"]["ready"] is False
    assert result["GBPUSD"]["missing"] == {"H1": 1}
    assert result["GBPUSD"]["details"]["H1"] == {"have": 29, "need": 30, "missing": 1}
    assert result["EURUSD"]["required"] == WARMUP_MIN_BARS
    assert WARMUP_MIN_BARS["H1"] == 30
    client.pipeline.assert_called_once_with(transaction=False)
    pipe.execute.assert_called_once_with()
    assert pipe.llen.call_args_list == [
        call(f"wolf15:candle_history:{symbol}:{tf}") for symbol in ["EURUSD", "GBPUSD"] for tf in WARMUP_MIN_BARS
    ]
    client.ping.assert_not_called()
    client.llen.assert_not_called()


def test_custom_requirements_and_single_symbol_parity(client: MagicMock) -> None:
    pipe = client.pipeline.return_value
    pipe.execute.return_value = [3, 1]
    client.llen.side_effect = [3, 1]
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
    client.pipeline.return_value.execute.return_value = [30, 10, 5, 5, 2]
    assert reader.check_warmup_many(["EURUSD"])["EURUSD"]["ready"] is True
    assert reader.read_source_ok is True
    assert reader.read_failure_count == 1


def test_single_symbol_uses_canonical_h1_threshold(client: MagicMock) -> None:
    client.llen.side_effect = [29, 10, 5, 5, 2]
    result = context_reader.RedisContextReader().check_warmup("EURUSD")
    assert result["ready"] is False
    assert result["missing"] == {"H1": 1}
    assert result["required"] == WARMUP_MIN_BARS
