"""Tests for heartbeat classifier and API route.

Covers:
- classify_heartbeat: ALIVE, STALE, MISSING, malformed payloads
- read_heartbeat: async Redis integration
- read_all_heartbeats: multi-service classification
- classify_ingest_health: split process/provider classification
- read_ingest_health: async Redis split-key integration
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
    IngestHealthState,
    IngestHealthStatus,
    classify_heartbeat,
    classify_ingest_health,
    read_all_heartbeats,
    read_heartbeat,
    read_ingest_health,
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

        def mock_get(key: str) -> str | None:
            if "process" in key:
                return orjson.dumps({"producer": "ingest_service", "ts": now - 2, "ws_connected": True}).decode()
            if "provider" in key:
                return orjson.dumps({"producer": "finnhub_ws", "ts": now - 2}).decode()
            return orjson.dumps({"producer": "ws", "ts": now - 2}).decode()

        mock_redis.get.side_effect = mock_get

        _check_ingest_heartbeat(mock_redis)

    def test_check_ingest_heartbeat_missing(self) -> None:
        """When ingest heartbeat is missing, should not raise."""
        from unittest.mock import MagicMock

        from startup.analysis_loop import _check_ingest_heartbeat

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        _check_ingest_heartbeat(mock_redis)  # Must not raise

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
                "ingest_process": HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="ingest_service",
                    last_ts=now - 3,
                ),
                "ingest_provider": HeartbeatStatus(
                    service="ingest_provider",
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

        async def mock_read_ingest(redis: Any) -> IngestHealthStatus:
            return IngestHealthStatus(
                state=IngestHealthState.HEALTHY,
                process=HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="ingest_service",
                    last_ts=now - 3,
                ),
                provider=HeartbeatStatus(
                    service="ingest_provider",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="finnhub_ws",
                    last_ts=now - 3,
                ),
            )

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
            patch("api.heartbeat_routes.read_ingest_health", side_effect=mock_read_ingest),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "HEALTHY"
        assert result["ingest_health"] == "HEALTHY"
        assert "timestamp" in result
        assert "ingest" in result["services"]
        assert "engine" in result["services"]
        assert result["services"]["ingest"]["state"] == "ALIVE"

    @pytest.mark.asyncio
    async def test_no_producer_response(self) -> None:
        """When ingest process is dead, overall should be NO_PRODUCER."""
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
                "ingest_process": HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.MISSING,
                    age_seconds=None,
                    producer=None,
                    last_ts=None,
                ),
                "ingest_provider": HeartbeatStatus(
                    service="ingest_provider",
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

        async def mock_read_ingest(redis: Any) -> IngestHealthStatus:
            return IngestHealthStatus(
                state=IngestHealthState.NO_PRODUCER,
                process=HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.MISSING,
                    age_seconds=None,
                    producer=None,
                    last_ts=None,
                ),
                provider=HeartbeatStatus(
                    service="ingest_provider",
                    state=HeartbeatState.MISSING,
                    age_seconds=None,
                    producer=None,
                    last_ts=None,
                ),
            )

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
            patch("api.heartbeat_routes.read_ingest_health", side_effect=mock_read_ingest),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "NO_PRODUCER"

    @pytest.mark.asyncio
    async def test_degraded_response(self) -> None:
        """When provider is stale but process alive, overall should be DEGRADED (weekend)."""
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
                "ingest_process": HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="ingest_service",
                    last_ts=now - 3,
                ),
                "ingest_provider": HeartbeatStatus(
                    service="ingest_provider",
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

        async def mock_read_ingest(redis: Any) -> IngestHealthStatus:
            return IngestHealthStatus(
                state=IngestHealthState.DEGRADED,
                process=HeartbeatStatus(
                    service="ingest_process",
                    state=HeartbeatState.ALIVE,
                    age_seconds=3.0,
                    producer="ingest_service",
                    last_ts=now - 3,
                ),
                provider=HeartbeatStatus(
                    service="ingest_provider",
                    state=HeartbeatState.STALE,
                    age_seconds=45.0,
                    producer="finnhub_ws",
                    last_ts=now - 45,
                ),
            )

        with (
            patch("api.heartbeat_routes.get_async_redis", new_callable=AsyncMock),
            patch("api.heartbeat_routes.read_all_heartbeats", side_effect=mock_read_all),
            patch("api.heartbeat_routes.read_ingest_health", side_effect=mock_read_ingest),
        ):
            from api.heartbeat_routes import heartbeat_status

            result = await heartbeat_status()

        assert result["overall"] == "DEGRADED"
        assert result["ingest_health"] == "DEGRADED"


# ══════════════════════════════════════════════════════════
#  classify_ingest_health — split heartbeat logic tests
# ══════════════════════════════════════════════════════════


class TestClassifyIngestHealth:
    """Test the tri-state ingest health classification."""

    def _make_status(self, service: str, state: HeartbeatState, age: float | None = 3.0) -> HeartbeatStatus:
        return HeartbeatStatus(
            service=service,
            state=state,
            age_seconds=age,
            producer="test",
            last_ts=time.time() - (age or 0),
        )

    def test_both_alive_is_healthy(self) -> None:
        process = self._make_status("ingest_process", HeartbeatState.ALIVE)
        provider = self._make_status("ingest_provider", HeartbeatState.ALIVE)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.HEALTHY

    def test_process_alive_provider_stale_is_degraded(self) -> None:
        """Weekend scenario: WS disconnected but process running."""
        process = self._make_status("ingest_process", HeartbeatState.ALIVE)
        provider = self._make_status("ingest_provider", HeartbeatState.STALE, age=120.0)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.DEGRADED

    def test_process_alive_provider_missing_is_degraded(self) -> None:
        """Provider never started (first deploy)."""
        process = self._make_status("ingest_process", HeartbeatState.ALIVE)
        provider = self._make_status("ingest_provider", HeartbeatState.MISSING, age=None)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.DEGRADED

    def test_process_stale_is_no_producer(self) -> None:
        """Process crashed — regardless of provider state."""
        process = self._make_status("ingest_process", HeartbeatState.STALE, age=60.0)
        provider = self._make_status("ingest_provider", HeartbeatState.ALIVE)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.NO_PRODUCER

    def test_both_missing_is_no_producer(self) -> None:
        """Service never deployed."""
        process = self._make_status("ingest_process", HeartbeatState.MISSING, age=None)
        provider = self._make_status("ingest_provider", HeartbeatState.MISSING, age=None)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.NO_PRODUCER

    def test_process_missing_provider_alive_is_no_producer(self) -> None:
        """Impossible in practice but should still be safe."""
        process = self._make_status("ingest_process", HeartbeatState.MISSING, age=None)
        provider = self._make_status("ingest_provider", HeartbeatState.ALIVE)
        result = classify_ingest_health(process, provider)
        assert result.state == IngestHealthState.NO_PRODUCER

    def test_result_is_frozen(self) -> None:
        process = self._make_status("ingest_process", HeartbeatState.ALIVE)
        provider = self._make_status("ingest_provider", HeartbeatState.ALIVE)
        result = classify_ingest_health(process, provider)
        assert isinstance(result, IngestHealthStatus)
        with pytest.raises(AttributeError):
            result.state = IngestHealthState.DEGRADED  # type: ignore[misc]


# ══════════════════════════════════════════════════════════
#  read_ingest_health — async Redis split-key tests
# ══════════════════════════════════════════════════════════


class TestReadIngestHealth:
    """Test read_ingest_health with mocked Redis."""

    @pytest.mark.asyncio
    async def test_healthy_when_both_fresh(self) -> None:
        now = time.time()
        redis = AsyncMock()

        async def mock_get(key: str) -> str | None:
            if "process" in key:
                return orjson.dumps({"producer": "ingest_service", "ts": now - 2}).decode()
            if "provider" in key:
                return orjson.dumps({"producer": "finnhub_ws", "ts": now - 3}).decode()
            return None

        redis.get.side_effect = mock_get
        result = await read_ingest_health(redis)
        assert result.state == IngestHealthState.HEALTHY

    @pytest.mark.asyncio
    async def test_degraded_when_provider_stale(self) -> None:
        """Weekend: process fresh, provider old."""
        now = time.time()
        redis = AsyncMock()

        async def mock_get(key: str) -> str | None:
            if "process" in key:
                return orjson.dumps({"producer": "ingest_service", "ts": now - 2}).decode()
            if "provider" in key:
                return orjson.dumps({"producer": "finnhub_ws", "ts": now - 120}).decode()
            return None

        redis.get.side_effect = mock_get
        result = await read_ingest_health(redis)
        assert result.state == IngestHealthState.DEGRADED

    @pytest.mark.asyncio
    async def test_no_producer_when_both_missing(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = None
        result = await read_ingest_health(redis)
        assert result.state == IngestHealthState.NO_PRODUCER
