from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.auth import verify_token
from api.redis_health_routes import router
from infrastructure.redis_health import build_extended_redis_report


@pytest.fixture()
def mock_redis() -> MagicMock:
    r = MagicMock()
    r.ping = AsyncMock(return_value=True)
    r.slowlog_len = AsyncMock(return_value=2)
    r.info = AsyncMock(
        side_effect=[
            {
                "instantaneous_ops_per_sec": 7,
                "expired_keys": 11,
                "evicted_keys": 0,
                "keyspace_hits": 101,
                "keyspace_misses": 4,
                "total_commands_processed": 222,
                "total_net_input_bytes": 333,
                "total_net_output_bytes": 444,
            },
            {
                "connected_clients": 3,
                "blocked_clients": 0,
            },
            {
                "used_memory": 123456,
                "used_memory_peak": 234567,
                "maxmemory": 0,
                "mem_fragmentation_ratio": 1.12,
            },
            {
                "rdb_last_bgsave_status": "ok",
                "rdb_last_bgsave_time_sec": 1,
                "rdb_changes_since_last_save": 0,
                "aof_enabled": 0,
                "aof_last_bgrewrite_status": "ok",
            },
            {
                "db0": {"keys": 17, "expires": 2, "avg_ttl": 0},
                "db1": {"keys": 5, "expires": 1, "avg_ttl": 0},
            },
        ]
    )
    return r


@pytest.fixture()
def app(mock_redis: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.state.redis = mock_redis
    application.dependency_overrides[verify_token] = lambda: {"sub": "test"}
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_build_extended_redis_report_aggregates_keyspace() -> None:
    report = build_extended_redis_report(
        pong=True,
        stats={"keyspace_hits": 10, "keyspace_misses": 2},
        clients={"connected_clients": 4, "blocked_clients": 1},
        memory={"used_memory": 100, "used_memory_peak": 200, "maxmemory": 300, "mem_fragmentation_ratio": 1.25},
        persistence={
            "rdb_last_bgsave_status": "ok",
            "rdb_last_bgsave_time_sec": 2,
            "rdb_changes_since_last_save": 3,
            "aof_enabled": 1,
            "aof_last_bgrewrite_status": "ok",
        },
        keyspace={
            "db0": {"keys": 7, "expires": 2},
            "db1": {"keys": 5, "expires": 1},
        },
        slowlog_len=9,
        latency_ms=12.345,
        timestamp="2026-04-21T00:00:00Z",
    )

    assert report["status"] == "ok"
    assert report["latency_ms"] == 12.35
    assert report["total_keys"] == 12
    assert report["keyspace_db_count"] == 2
    assert report["keyspace_expires"] == 3
    assert report["aof_enabled"] is True


def test_redis_health_extended_returns_expected_payload(client: TestClient, mock_redis: MagicMock) -> None:
    resp: httpx.Response = client.get("/api/v1/redis/health/extended")

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["status"] == "ok"
    assert body["connected_clients"] == 3
    assert body["blocked_clients"] == 0
    assert body["used_memory"] == 123456
    assert body["used_memory_peak"] == 234567
    assert body["mem_fragmentation_ratio"] == 1.12
    assert body["total_keys"] == 22
    assert body["rdb_last_bgsave_status"] == "ok"
    assert body["rdb_last_bgsave_time_sec"] == 1
    assert body["aof_enabled"] is False
    assert body["slowlog_len"] == 2
    assert "timestamp" in body
    assert mock_redis.info.await_count == 5


def test_redis_health_extended_returns_503_on_info_failure(client: TestClient, mock_redis: MagicMock) -> None:
    mock_redis.info = AsyncMock(side_effect=RuntimeError("info unavailable"))

    resp: httpx.Response = client.get("/api/v1/redis/health/extended")

    assert resp.status_code == 503
    assert "Redis extended health check failed" in resp.json()["detail"]