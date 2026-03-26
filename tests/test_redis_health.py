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
