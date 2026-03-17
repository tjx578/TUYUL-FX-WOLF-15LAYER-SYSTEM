"""Tests for storage/startup.py — Redis empty detection and recovery routing.

Covers:
  - _has_candle_data correctly detects candle history keys via SCAN
  - init_persistent_storage routes to full recovery when Redis is truly empty
  - init_persistent_storage routes to risk-state-only recovery when candles
    exist but risk data is missing
  - init_persistent_storage skips recovery entirely when Redis has all data
"""

from __future__ import annotations

import fnmatch
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────
#  FakeRedisClient — minimal sync interface matching storage.redis_client
# ──────────────────────────────────────────────────────────────────


class _FakeSyncClient:
    """Minimal sync Redis client with SCAN support (used via .client)."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def scan(self, cursor: int = 0, match: str = "*", count: int = 50) -> tuple[int, list[str]]:
        matched = [k for k in self._keys if fnmatch.fnmatch(k, match)]
        return (0, matched)


class FakeRedis:
    """Sync RedisClient stub exposing .get and .client.scan."""

    def __init__(self, store: dict[str, str], candle_keys: list[str] | None = None) -> None:
        self._store = store
        self.client = _FakeSyncClient(candle_keys or [])

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


# ──────────────────────────────────────────────────────────────────
#  _has_candle_data unit tests
# ──────────────────────────────────────────────────────────────────


class TestHasCandleData:
    def test_returns_true_when_candle_key_present(self) -> None:
        """SCAN matching wolf15:candle_history:* → True."""
        from storage.startup import _has_candle_data

        redis = FakeRedis(store={}, candle_keys=["wolf15:candle_history:EURUSD:H1"])
        assert _has_candle_data(redis) is True  # type: ignore[arg-type]

    def test_returns_false_when_no_candle_keys(self) -> None:
        """Empty SCAN result → False."""
        from storage.startup import _has_candle_data

        redis = FakeRedis(store={}, candle_keys=[])
        assert _has_candle_data(redis) is False  # type: ignore[arg-type]

    def test_returns_false_on_scan_exception(self) -> None:
        """Exception during SCAN → False (fail safe, no crash)."""
        from storage.startup import _has_candle_data

        class ErrorSyncClient:
            def scan(self, *args: Any, **kwargs: Any) -> tuple[int, list[str]]:
                raise ConnectionError("Redis unreachable")

        redis = MagicMock()
        redis.client = ErrorSyncClient()
        assert _has_candle_data(redis) is False

    def test_ignores_non_candle_keys(self) -> None:
        """Keys that don't match wolf15:candle_history:* must not affect result."""
        from storage.startup import _has_candle_data

        redis = FakeRedis(
            store={},
            candle_keys=["wolf15:peak_equity", "wolf15:drawdown:daily"],
        )
        assert _has_candle_data(redis) is False


# ──────────────────────────────────────────────────────────────────
#  init_persistent_storage recovery routing
# ──────────────────────────────────────────────────────────────────


class TestInitPersistentStorageRecoveryRouting:
    """Validate which PersistenceSync recovery method is called under each condition."""

    def _make_sync_service(self, recover_from_pg: AsyncMock, recover_risk_only: AsyncMock) -> Any:
        svc = MagicMock()
        svc.recover_from_postgres = recover_from_pg
        svc.recover_risk_state_only = recover_risk_only
        svc.run = AsyncMock(return_value=None)
        return svc

    @pytest.mark.asyncio
    async def test_full_recovery_when_redis_truly_empty(self) -> None:
        """No candle keys + no peak_equity → full recover_from_postgres."""
        recover_from_pg = AsyncMock(return_value=True)
        recover_risk_only = AsyncMock(return_value=True)

        redis = FakeRedis(store={}, candle_keys=[])
        svc = self._make_sync_service(recover_from_pg, recover_risk_only)

        fake_pg = MagicMock()
        fake_pg.is_available = True
        fake_pg.initialize = AsyncMock()

        with (
            patch("storage.startup.pg_client", fake_pg),
            patch("storage.startup.RedisClient", return_value=redis),
            patch("storage.startup.PersistenceSync", return_value=svc),
            patch("storage.startup.asyncio.create_task"),
        ):
            from storage import startup

            startup._sync_service = None
            startup._sync_task = None
            await startup.init_persistent_storage()

        recover_from_pg.assert_awaited_once()
        recover_risk_only.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_risk_only_recovery_when_candles_exist_no_risk(self) -> None:
        """Candle keys present + no peak_equity → recover_risk_state_only."""
        recover_from_pg = AsyncMock(return_value=True)
        recover_risk_only = AsyncMock(return_value=True)

        redis = FakeRedis(
            store={},  # no peak_equity
            candle_keys=["wolf15:candle_history:EURUSD:H1"],
        )
        svc = self._make_sync_service(recover_from_pg, recover_risk_only)

        fake_pg = MagicMock()
        fake_pg.is_available = True
        fake_pg.initialize = AsyncMock()

        with (
            patch("storage.startup.pg_client", fake_pg),
            patch("storage.startup.RedisClient", return_value=redis),
            patch("storage.startup.PersistenceSync", return_value=svc),
            patch("storage.startup.asyncio.create_task"),
        ):
            from storage import startup

            startup._sync_service = None
            startup._sync_task = None
            await startup.init_persistent_storage()

        recover_risk_only.assert_awaited_once()
        recover_from_pg.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_recovery_when_redis_has_all_data(self) -> None:
        """Candle keys present + peak_equity present → no recovery."""
        recover_from_pg = AsyncMock(return_value=True)
        recover_risk_only = AsyncMock(return_value=True)

        redis = FakeRedis(
            store={"wolf15:peak_equity": "100000.0"},
            candle_keys=["wolf15:candle_history:EURUSD:H1"],
        )
        svc = self._make_sync_service(recover_from_pg, recover_risk_only)

        fake_pg = MagicMock()
        fake_pg.is_available = True
        fake_pg.initialize = AsyncMock()

        with (
            patch("storage.startup.pg_client", fake_pg),
            patch("storage.startup.RedisClient", return_value=redis),
            patch("storage.startup.PersistenceSync", return_value=svc),
            patch("storage.startup.asyncio.create_task"),
        ):
            from storage import startup

            startup._sync_service = None
            startup._sync_task = None
            await startup.init_persistent_storage()

        recover_from_pg.assert_not_awaited()
        recover_risk_only.assert_not_awaited()
