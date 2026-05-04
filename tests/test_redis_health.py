from __future__ import annotations

import logging

import pytest

import infrastructure.redis_health as redis_health


class _FakePool:
    def __init__(self, *, available: int, in_use: int, max_connections: int) -> None:
        self._available_connections = [object() for _ in range(available)]
        self._in_use_connections = [object() for _ in range(in_use)]
        self.max_connections = max_connections


class _FakeAsyncManager:
    def __init__(self, pool: _FakePool, healthy: bool = True) -> None:
        self._pool = pool
        self._healthy = healthy

    async def health_check(self) -> bool:
        return self._healthy


class _FakeBlockingPool:
    max_connections = 10

    def __init__(self) -> None:
        self._free = [object(), object()]
        self._used = [object(), object(), object()]
        self._connections = [*self._free, *self._used]

    def _get_free_connections(self) -> set[object]:
        return set(self._free)

    def _get_in_use_connections(self) -> set[object]:
        return set(self._used)


def _has_low_connection_warning(caplog: pytest.LogCaptureFixture) -> bool:
    return any("Low available connections" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_async_health_does_not_warn_when_idle_low_but_headroom_high(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import infrastructure.redis_client as redis_client

    pool = _FakePool(available=1, in_use=0, max_connections=20)
    monkeypatch.setattr(redis_client, "_manager", _FakeAsyncManager(pool), raising=False)

    with caplog.at_level(logging.WARNING, logger=redis_health.logger.name):
        report = await redis_health.check_redis_pool_health()

    assert report["healthy"] is True
    assert report["pool_headroom"] == 20
    assert not _has_low_connection_warning(caplog)


@pytest.mark.asyncio
async def test_async_health_warns_when_headroom_is_low(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import infrastructure.redis_client as redis_client

    pool = _FakePool(available=1, in_use=19, max_connections=20)
    monkeypatch.setattr(redis_client, "_manager", _FakeAsyncManager(pool), raising=False)

    with caplog.at_level(logging.WARNING, logger=redis_health.logger.name):
        report = await redis_health.check_redis_pool_health()

    assert report["healthy"] is True
    assert report["pool_headroom"] == 1
    assert _has_low_connection_warning(caplog)


def test_sync_health_does_not_warn_when_idle_low_but_headroom_high(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import storage.redis_client as storage_redis_client

    class _FakeSyncClient:
        def __init__(self) -> None:
            self._pool = _FakePool(available=1, in_use=0, max_connections=20)

        def ping(self) -> bool:
            return True

    monkeypatch.setattr(storage_redis_client, "RedisClient", _FakeSyncClient)

    with caplog.at_level(logging.WARNING, logger=redis_health.logger.name):
        report = redis_health.check_sync_redis_pool_health()

    assert report["healthy"] is True
    assert report["pool_headroom"] == 20
    assert not _has_low_connection_warning(caplog)


def test_pool_metrics_supports_blocking_pool_helpers() -> None:
    available, in_use, created, max_conns, headroom = redis_health._compute_pool_metrics(_FakeBlockingPool())

    assert available == 2
    assert in_use == 3
    assert created == 5
    assert max_conns == 10
    assert headroom == 7


def test_extended_report_includes_connection_and_buffer_pressure() -> None:
    report = redis_health.build_extended_redis_report(
        pong=True,
        stats={
            "instantaneous_ops_per_sec": 42,
            "rejected_connections": 2,
            "total_connections_received": 100,
            "instantaneous_input_kbps": 12.5,
            "instantaneous_output_kbps": 20.25,
        },
        clients={
            "connected_clients": 5,
            "blocked_clients": 1,
            "maxclients": 10,
            "client_recent_max_input_buffer": 1024,
            "client_recent_max_output_buffer": 2048,
        },
        memory={
            "used_memory": 256,
            "used_memory_peak": 512,
            "maxmemory": 1024,
            "mem_fragmentation_ratio": 1.25,
        },
        persistence={},
        keyspace={"db0": {"keys": 3, "expires": 1}},
        slowlog_len=0,
        latency_ms=1.234,
        timestamp="2026-05-04T00:00:00+00:00",
    )

    assert report["status"] == "ok"
    assert report["rejected_connections"] == 2
    assert report["client_used_ratio"] == 0.5
    assert report["memory_used_ratio"] == 0.25
    assert report["memory_headroom_bytes"] == 768
    assert report["client_recent_max_output_buffer"] == 2048
