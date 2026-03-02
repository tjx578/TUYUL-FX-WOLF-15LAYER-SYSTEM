"""Tests for Redis candle-cache flush endpoints.

Covers:
- DELETE /api/v1/redis/candles           (flush all candle keys)
- DELETE /api/v1/redis/candles/{symbol}/{timeframe}  (flush specific pair)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.redis_health_routes import delete_keys_by_pattern, router


def _delete(client: TestClient, url: str) -> httpx.Response:
    """Typed wrapper around TestClient.delete to satisfy strict type checkers."""
    return client.request("DELETE", url)

# ---------------------------------------------------------------------------
# App fixture — minimal FastAPI with the redis_health router
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> MagicMock:
    r = MagicMock()
    r.ping = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=0)
    r.scan = AsyncMock(return_value=(0, []))
    r.info = AsyncMock(return_value={})
    r.slowlog_len = AsyncMock(return_value=0)
    return r


@pytest.fixture()
def app(mock_redis: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.state.redis = mock_redis
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit test: _delete_keys_by_pattern helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_keys_by_pattern_no_keys() -> None:
    """Returns 0 when no keys match the pattern."""
    r = MagicMock()
    r.scan = AsyncMock(return_value=(0, []))
    r.delete = AsyncMock(return_value=0)

    result = await delete_keys_by_pattern(r, "candles:*")

    assert result == 0
    r.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_keys_by_pattern_with_keys() -> None:
    """Deletes all keys returned by SCAN and returns correct count."""
    r = MagicMock()
    # First SCAN page returns two keys; second page (cursor=0) ends iteration
    r.scan = AsyncMock(side_effect=[
        (42, ["candles:EURUSD:M15", "candles:GBPUSD:M15"]),
        (0, []),
    ])
    r.delete = AsyncMock(return_value=2)

    result = await delete_keys_by_pattern(r, "candles:*")

    assert result == 2
    r.delete.assert_called_once_with("candles:EURUSD:M15", "candles:GBPUSD:M15")


@pytest.mark.asyncio
async def test_delete_keys_by_pattern_multiple_pages() -> None:
    """Accumulates deletions across multiple SCAN pages."""
    r = MagicMock()
    r.scan = AsyncMock(side_effect=[
        (99, ["k1", "k2"]),
        (0, ["k3"]),
    ])
    r.delete = AsyncMock(side_effect=[2, 1])

    result = await delete_keys_by_pattern(r, "*")

    assert result == 3


# ---------------------------------------------------------------------------
# DELETE /api/v1/redis/candles — flush all
# ---------------------------------------------------------------------------


def test_flush_all_candles_returns_ok(client: TestClient, mock_redis: MagicMock) -> None:
    mock_redis.scan = AsyncMock(return_value=(0, []))

    resp = _delete(client, "/api/v1/redis/candles")

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["status"] == "ok"
    assert body["deleted_count"] == 0
    assert "flushed_at" in body


def test_flush_all_candles_counts_deleted_keys(client: TestClient, mock_redis: MagicMock) -> None:
    """Reports the total number of keys deleted across all prefixes."""
    mock_redis.scan = AsyncMock(return_value=(0, ["k1", "k2", "k3"]))
    mock_redis.delete = AsyncMock(return_value=3)

    resp = _delete(client, "/api/v1/redis/candles")

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert mock_redis.scan.await_count > 0
    assert body["deleted_count"] == mock_redis.scan.await_count * 3


def test_flush_all_candles_covers_all_prefixes(client: TestClient, mock_redis: MagicMock) -> None:
    """SCAN is called once per candle-cache prefix."""
    scan_patterns: list[str] = []

    async def capture_scan(cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        scan_patterns.append(match)
        return (0, [])

    mock_redis.scan = AsyncMock(side_effect=capture_scan)

    _delete(client, "/api/v1/redis/candles")

    assert scan_patterns
    assert len(scan_patterns) == len(set(scan_patterns))
    assert all(pattern.endswith(":*") for pattern in scan_patterns)


# ---------------------------------------------------------------------------
# DELETE /api/v1/redis/candles/{symbol}/{timeframe} — flush specific pair
# ---------------------------------------------------------------------------


def test_flush_pair_returns_ok(client: TestClient, mock_redis: MagicMock) -> None:
    mock_redis.delete = AsyncMock(return_value=1)

    resp = _delete(client, "/api/v1/redis/candles/EURUSD/M15")

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["status"] == "ok"
    assert body["symbol"] == "EURUSD"
    assert body["timeframe"] == "M15"
    assert body["deleted_count"] == 1
    assert "flushed_at" in body


def test_flush_pair_deletes_all_prefix_keys(client: TestClient, mock_redis: MagicMock) -> None:
    """DELETE is called with keys for every known prefix."""
    mock_redis.delete = AsyncMock(return_value=2)

    _delete(client, "/api/v1/redis/candles/USDCHF/M15")

    call_args: tuple[object, ...] = mock_redis.delete.call_args[0]
    keys: list[str] = [str(arg) for arg in call_args]
    assert keys
    assert len(keys) == len(set(keys))
    assert all(key.endswith(":USDCHF:M15") for key in keys)


def test_flush_pair_normalises_case(client: TestClient, mock_redis: MagicMock) -> None:
    """Symbol and timeframe are uppercased regardless of input case."""
    mock_redis.delete = AsyncMock(return_value=0)

    resp = _delete(client, "/api/v1/redis/candles/eurusd/m15")

    body: dict[str, Any] = resp.json()
    assert body["symbol"] == "EURUSD"
    assert body["timeframe"] == "M15"


def test_flush_pair_zero_deleted_is_still_ok(client: TestClient, mock_redis: MagicMock) -> None:
    """Returns ok even when no keys existed for that pair."""
    mock_redis.delete = AsyncMock(return_value=0)

    resp: httpx.Response = _delete(client, "/api/v1/redis/candles/GBPUSD/H1")

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["deleted_count"] == 0


def test_flush_pair_rejects_invalid_symbol(client: TestClient, mock_redis: MagicMock) -> None:
    """Returns 422 when the symbol contains non-alphanumeric characters."""
    resp = _delete(client, "/api/v1/redis/candles/EUR*USD/M15")

    assert resp.status_code == 422


def test_flush_pair_rejects_invalid_timeframe(client: TestClient, mock_redis: MagicMock) -> None:
    """Returns 422 when the timeframe does not match the expected pattern."""
    resp = _delete(client, "/api/v1/redis/candles/EURUSD/1M5X")

    assert resp.status_code == 422  # noqa: WPS432
