"""Batch verdict reads preserve missing rows and fail closed on read errors."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import redis

from storage import l12_cache


@pytest.fixture(autouse=True)
def reset_read_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(l12_cache, "_READ_REDIS_UNAVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(l12_cache, "_READ_REDIS_FAILURE_COUNT", 0)
    monkeypatch.setattr(l12_cache.time, "monotonic", lambda: 100.0)
    monkeypatch.setenv("L12_CACHE_READ_REDIS_FAILURE_COOLDOWN_SEC", "1.0")


def test_batch_reads_once_and_keeps_missing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock(spec=["mget"])
    client.mget.return_value = [b'{"verdict":"HOLD"}', None, '{"verdict":"BLOCK"}']
    factory = Mock(return_value=client)
    monkeypatch.setattr(l12_cache, "_read_redis_client", factory)

    assert l12_cache.get_verdicts(["EURUSD", "GBPUSD", "USDJPY"]) == {
        "EURUSD": {"verdict": "HOLD"},
        "GBPUSD": None,
        "USDJPY": {"verdict": "BLOCK"},
    }
    factory.assert_called_once_with()
    client.mget.assert_called_once_with(["L12:VERDICT:EURUSD", "L12:VERDICT:GBPUSD", "L12:VERDICT:USDJPY"])
    assert l12_cache.verdict_read_source_ok()
    assert l12_cache.verdict_read_failure_count() == 0


@pytest.mark.parametrize("cooldown", [False, True])
def test_empty_or_cooldown_batch_does_not_connect(monkeypatch: pytest.MonkeyPatch, cooldown: bool) -> None:
    factory = Mock(side_effect=AssertionError("Unexpected Redis connection"))
    monkeypatch.setattr(l12_cache, "_read_redis_client", factory)
    if cooldown:
        monkeypatch.setattr(l12_cache, "_READ_REDIS_UNAVAILABLE_UNTIL", 101.0)
    pairs = ["EURUSD"] if cooldown else []
    assert l12_cache.get_verdicts(pairs) == dict.fromkeys(pairs)
    factory.assert_not_called()
    assert l12_cache.verdict_read_failure_count() == 0


@pytest.mark.parametrize("error", [redis.ConnectionError("offline"), redis.TimeoutError("deadline")])
def test_batch_failure_enters_cooldown_and_recovers(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    client = Mock(spec=["mget"])
    client.mget.side_effect = [error, [b'{"verdict":"HOLD"}']]
    monkeypatch.setattr(l12_cache, "_read_redis_client", lambda: client)

    assert l12_cache.get_verdicts(["EURUSD"]) == {"EURUSD": None}
    assert not l12_cache.verdict_read_source_ok()
    assert l12_cache.verdict_read_failure_count() == 1
    assert l12_cache.get_verdicts(["EURUSD"]) == {"EURUSD": None}
    assert client.mget.call_count == 1

    monkeypatch.setattr(l12_cache.time, "monotonic", lambda: 102.0)
    assert l12_cache.get_verdicts(["EURUSD"]) == {"EURUSD": {"verdict": "HOLD"}}
    assert l12_cache.verdict_read_source_ok()
    assert l12_cache.verdict_read_failure_count() == 1
    assert client.mget.call_count == 2


@pytest.mark.parametrize("raw", [b"not-json", b"\xff", b"[]", b"null", b"", 123])
def test_malformed_entry_fails_whole_batch_closed(monkeypatch: pytest.MonkeyPatch, raw: object) -> None:
    client = Mock(spec=["mget"])
    client.mget.return_value = [b'{"verdict":"HOLD"}', raw]
    monkeypatch.setattr(l12_cache, "_read_redis_client", lambda: client)

    assert l12_cache.get_verdicts(["EURUSD", "GBPUSD"]) == {"EURUSD": None, "GBPUSD": None}
    assert not l12_cache.verdict_read_source_ok()
    assert l12_cache.verdict_read_failure_count() == 1
    assert client.mget.call_count == 1


@pytest.mark.parametrize("response", [None, [], [None, None], "invalid"])
def test_malformed_batch_response_is_not_a_cache_miss(monkeypatch: pytest.MonkeyPatch, response: object) -> None:
    client = Mock(spec=["mget"])
    client.mget.return_value = response
    monkeypatch.setattr(l12_cache, "_read_redis_client", lambda: client)
    assert l12_cache.get_verdicts(["EURUSD"]) == {"EURUSD": None}
    assert l12_cache.verdict_read_failure_count() == 1


def test_legacy_single_key_read_remains_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = Mock(return_value=b'{"verdict":"HOLD"}')
    monkeypatch.setattr(l12_cache, "_read_cache_value", reader)
    assert l12_cache.get_verdict("EURUSD") == {"verdict": "HOLD"}
    reader.assert_called_once_with("L12:VERDICT:EURUSD")
