"""Tests for heartbeat classifier and API route.

Covers:
- classify_heartbeat: ALIVE, STALE, MISSING, malformed payloads
- read_heartbeat: async Redis integration
- read_all_heartbeats: multi-service classification
- API endpoint: /api/v1/heartbeat/status
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from state.heartbeat_classifier import (
    HeartbeatState,
    HeartbeatStatus,
    classify_heartbeat,
    read_all_heartbeats,
    read_heartbeat,
)

# ══════════════════════════════════════════════════════════
#  classify_heartbeat — pure function tests
# ══════════════════════════════════════════════════════════


class TestClassifyHeartbeat:
    """Test classify_heartbeat pure function."""

    def test_none_payload_returns_missing(self) -> None:
        result = classify_heartbeat(None, max_age_sec=30, service="ingest")
        assert result.state == HeartbeatState.MISSING
        assert result.age_seconds is None
        assert result.producer is None
        assert result.last_ts is None
        assert result.service == "ingest"

    def test_alive_heartbeat(self) -> None:
        now = time.time()
        payload = orjson.dumps({"producer": "finnhub_ws", "ts": now - 5})
        result = classify_heartbeat(payload, max_age_sec=30, service="ingest", now_ts=now)
        assert result.state == HeartbeatState.ALIVE
        assert result.age_seconds == 5.0
        assert result.producer == "finnhub_ws"
        assert result.last_ts == pytest.approx(now - 5, abs=0.01)

    def test_stale_heartbeat(self) -> None:
        now = time.time()
        payload = orjson.dumps({"producer": "finnhub_ws", "ts": now - 60})
        result = classify_heartbeat(payload, max_age_sec=30, service="ingest", now_ts=now)
        assert result.state == HeartbeatState.STALE
        assert result.age_seconds == 60.0
        assert result.producer == "finnhub_ws"

    def test_exact_threshold_is_alive(self) -> None:
        """Age exactly at threshold is still ALIVE (<=)."""
        now = time.time()
        payload = orjson.dumps({"producer": "test", "ts": now - 30})
        result = classify_heartbeat(payload, max_age_sec=30, service="test", now_ts=now)
        assert result.state == HeartbeatState.ALIVE

    def test_just_over_threshold_is_stale(self) -> None:
        now = time.time()
        payload = orjson.dumps({"producer": "test", "ts": now - 30.01})
        result = classify_heartbeat(payload, max_age_sec=30, service="test", now_ts=now)
        assert result.state == HeartbeatState.STALE

    def test_malformed_json_returns_missing(self) -> None:
        result = classify_heartbeat(b"not json", max_age_sec=30, service="ingest")
        assert result.state == HeartbeatState.MISSING
        assert result.age_seconds is None

    def test_missing_ts_field_returns_missing(self) -> None:
        payload = orjson.dumps({"producer": "test"})
        result = classify_heartbeat(payload, max_age_sec=30, service="ingest")
        assert result.state == HeartbeatState.MISSING
        assert result.producer == "test"

    def test_invalid_ts_type_returns_missing(self) -> None:
        payload = orjson.dumps({"producer": "test", "ts": "not_a_number"})
        result = classify_heartbeat(payload, max_age_sec=30, service="ingest")
        assert result.state == HeartbeatState.MISSING

    def test_string_payload(self) -> None:
        """Accept string (not just bytes)."""
        now = time.time()
        payload = orjson.dumps({"producer": "ws", "ts": now - 2}).decode("utf-8")
        result = classify_heartbeat(payload, max_age_sec=30, service="ingest", now_ts=now)
        assert result.state == HeartbeatState.ALIVE

    def test_future_timestamp_clamps_to_zero(self) -> None:
        """A timestamp in the future should produce age=0, still ALIVE."""
        now = time.time()
        payload = orjson.dumps({"producer": "test", "ts": now + 100})
        result = classify_heartbeat(payload, max_age_sec=30, service="test", now_ts=now)
        assert result.state == HeartbeatState.ALIVE
        assert result.age_seconds == 0.0

    def test_status_is_frozen_dataclass(self) -> None:
        result = classify_heartbeat(None, max_age_sec=30, service="test")
        assert isinstance(result, HeartbeatStatus)
        with pytest.raises(AttributeError):
            result.state = HeartbeatState.ALIVE  # type: ignore[misc]


# ══════════════════════════════════════════════════════════
#  read_heartbeat — async Redis mock tests
# ══════════════════════════════════════════════════════════


class TestReadHeartbeat:
    """Test read_heartbeat async function with mocked Redis."""

    @pytest.mark.asyncio
    async def test_alive_from_redis(self) -> None:
        now = time.time()
        redis = AsyncMock()
        redis.get.return_value = orjson.dumps({"producer": "ws", "ts": now - 3}).decode()

        result = await read_heartbeat(redis, "wolf15:heartbeat:ingest", 30, service="ingest")
        assert result.state == HeartbeatState.ALIVE
        redis.get.assert_awaited_once_with("wolf15:heartbeat:ingest")

    @pytest.mark.asyncio
    async def test_missing_key_from_redis(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = None

        result = await read_heartbeat(redis, "wolf15:heartbeat:ingest", 30, service="ingest")
        assert result.state == HeartbeatState.MISSING

    @pytest.mark.asyncio
    async def test_redis_error_returns_missing(self) -> None:
        redis = AsyncMock()
        redis.get.side_effect = ConnectionError("Redis down")

        result = await read_heartbeat(redis, "wolf15:heartbeat:ingest", 30, service="ingest")
        assert result.state == HeartbeatState.MISSING

    @pytest.mark.asyncio
    async def test_stale_from_redis(self) -> None:
        now = time.time()
        redis = AsyncMock()
        redis.get.return_value = orjson.dumps({"producer": "ws", "ts": now - 120}).decode()

        result = await read_heartbeat(redis, "wolf15:heartbeat:engine", 60, service="engine")
        assert result.state == HeartbeatState.STALE


# ══════════════════════════════════════════════════════════
#  read_all_heartbeats — multi-service tests
# ══════════════════════════════════════════════════════════


class TestReadAllHeartbeats:
    """Test read_all_heartbeats aggregation."""

    @pytest.mark.asyncio
    async def test_all_services_returned(self) -> None:
        now = time.time()
        redis = AsyncMock()

        async def mock_get(key: str) -> str | None:
            if "ingest" in key:
                return orjson.dumps({"producer": "ws", "ts": now - 2}).decode()
            if "engine" in key:
                return orjson.dumps({"producer": "engine_analysis", "ts": now - 5}).decode()
            return None

        redis.get.side_effect = mock_get

        results = await read_all_heartbeats(redis)
        assert "ingest" in results
        assert "engine" in results
        assert results["ingest"].state == HeartbeatState.ALIVE
        assert results["engine"].state == HeartbeatState.ALIVE

    @pytest.mark.asyncio
    async def test_mixed_states(self) -> None:
        now = time.time()
        redis = AsyncMock()

        async def mock_get(key: str) -> str | None:
            if "ingest" in key:
                return None  # Missing
            if "engine" in key:
                return orjson.dumps({"producer": "engine_analysis", "ts": now - 2}).decode()
            return None

        redis.get.side_effect = mock_get

        results = await read_all_heartbeats(redis)
        assert results["ingest"].state == HeartbeatState.MISSING
        assert results["engine"].state == HeartbeatState.ALIVE


# ══════════════════════════════════════════════════════════
#  Engine heartbeat check function
# ══════════════════════════════════════════════════════════


class TestEngineHeartbeatCheck:
    """Test _check_ingest_heartbeat function from analysis_loop."""

    def test_check_ingest_heartbeat_alive(self) -> None:
        """When ingest heartbeat is fresh, metrics should show alive."""
        from unittest.mock import MagicMock

        from startup.analysis_loop import _check_ingest_heartbeat

        now = time.time()
        mock_redis = MagicMock()
        mock_redis.get.return_value = orjson.dumps({"producer": "ws", "ts": now - 2}).decode()

        _check_ingest_heartbeat(mock_redis)
        mock_redis.get.assert_called_once()

    def test_check_ingest_heartbeat_missing(self) -> None:
        """When ingest heartbeat is missing, should not raise."""
        from unittest.mock import MagicMock

        from startup.analysis_loop import _check_ingest_heartbeat

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        _check_ingest_heartbeat(mock_redis)  # Must not raise
        mock_redis.get.assert_called_once()

    def test_check_ingest_heartbeat_redis_error(self) -> None:
        """Redis error should not crash the check."""
        from unittest.mock import MagicMock

        from startup.analysis_loop import _check_ingest_heartbeat

        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Redis down")

        _check_ingest_heartbeat(mock_redis)  # Must not raise


# ══════════════════════════════════════════════════════════
#  API route tests
# ══════════════════════════════════════════════════════════


class TestHeartbeatRoute:
    """Test /api/v1/heartbeat/status endpoint logic."""

    @pytest.mark.asyncio
    async def test_healthy_response_shape(self) -> None:
        """Verify response includes overall, timestamp, and services."""
        from unittest.mock import patch

        now = time.time()

        async def mock_read_all(redis: Any) -> dict[str, HeartbeatStatus]:
            return {
                "ingest": HeartbeatStatus(
                    service="ingest",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="finnhub_ws",
                    last_ts=now - 3,
                ),
                "engine": HeartbeatStatus(
                    service="engine",
                    state=HeartbeatState.ALIVE,
                    age_seconds=5.0,
                    producer="engine_analysis",
                    last_ts=now - 5,
                ),
            }

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "HEALTHY"
        assert "timestamp" in result
        assert "ingest" in result["services"]
        assert "engine" in result["services"]
        assert result["services"]["ingest"]["state"] == "ALIVE"

    @pytest.mark.asyncio
    async def test_no_producer_response(self) -> None:
        """When a service is missing, overall should be NO_PRODUCER."""
        from unittest.mock import patch

        now = time.time()

        async def mock_read_all(redis: Any) -> dict[str, HeartbeatStatus]:
            return {
                "ingest": HeartbeatStatus(
                    service="ingest",
                    state=HeartbeatState.MISSING,
                    age_seconds=None,
                    producer=None,
                    last_ts=None,
                ),
                "engine": HeartbeatStatus(
                    service="engine",
                    state=HeartbeatState.ALIVE,
                    age_seconds=5.0,
                    producer="engine_analysis",
                    last_ts=now - 5,
                ),
            }

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "NO_PRODUCER"

    @pytest.mark.asyncio
    async def test_degraded_response(self) -> None:
        """When a service is stale, overall should be DEGRADED."""
        from unittest.mock import patch

        now = time.time()

        async def mock_read_all(redis: Any) -> dict[str, HeartbeatStatus]:
            return {
                "ingest": HeartbeatStatus(
                    service="ingest",
                    state=HeartbeatState.STALE,
                    age_seconds=45.0,
                    producer="finnhub_ws",
                    last_ts=now - 45,
                ),
                "engine": HeartbeatStatus(
                    service="engine",
                    state=HeartbeatState.ALIVE,
                    age_seconds=5.0,
                    producer="engine_analysis",
                    last_ts=now - 5,
                ),
            }

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "DEGRADED"
