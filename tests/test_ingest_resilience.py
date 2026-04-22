"""Focused ingest resilience tests for readiness and stale-cache behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from infrastructure.circuit_breaker import CircuitBreaker, CircuitState
from ingest import service_metrics, warmup_bootstrap


@pytest.fixture(autouse=True)
def reset_ingest_service_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_metrics, "ingest_ready", False)
    monkeypatch.setattr(service_metrics, "ingest_degraded", False)
    monkeypatch.setattr(service_metrics, "startup_mode", "unknown")
    monkeypatch.setattr(service_metrics, "enabled_symbol_count", 0)
    monkeypatch.setattr(service_metrics, "producer_present", False)
    monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", 0.0)
    monkeypatch.setattr(service_metrics, "pair_last_tick_ts", {})
    monkeypatch.setattr(service_metrics, "_last_logged_ingest_state", "")
    monkeypatch.setattr(service_metrics, "_last_logged_reason", "")
    monkeypatch.setattr(service_metrics, "_last_logged_blocked_by", "")


def _fresh_ticks(count: int) -> dict[str, float]:
    now = service_metrics.time()
    return {f"PAIR{i}": now for i in range(count)}


class TestIngestReadinessDegradedMode:
    """Readiness should follow runtime conditions, not stale startup flags alone."""

    def test_readiness_false_when_bootstrap_never_completed(self) -> None:
        assert service_metrics.ingest_readiness() is False

    def test_readiness_true_when_runtime_live_conditions_recover_from_stale_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(service_metrics, "startup_mode", "stale_cache")
        monkeypatch.setattr(service_metrics, "ingest_degraded", True)
        monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
        monkeypatch.setattr(service_metrics, "producer_present", True)
        monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", service_metrics.time())
        monkeypatch.setattr(service_metrics, "pair_last_tick_ts", _fresh_ticks(26))

        assert service_metrics.ingest_readiness() is True
        snapshot = service_metrics.build_runtime_snapshot(ws_connected=True)
        assert snapshot["ready"] is True
        assert snapshot["degraded"] is False
        assert snapshot["ingest_state"] == "LIVE"
        assert snapshot["fresh_pair_target"] == 26

    def test_readiness_false_when_producer_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(service_metrics, "startup_mode", "warmup")
        monkeypatch.setattr(service_metrics, "ingest_ready", True)
        monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
        monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", service_metrics.time())
        monkeypatch.setattr(service_metrics, "pair_last_tick_ts", _fresh_ticks(30))

        assert service_metrics.ingest_readiness() is False

    def test_readiness_false_when_producer_heartbeat_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(service_metrics, "startup_mode", "warmup")
        monkeypatch.setattr(service_metrics, "ingest_ready", True)
        monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
        monkeypatch.setattr(service_metrics, "producer_present", True)
        monkeypatch.setattr(
            service_metrics,
            "producer_last_heartbeat_ts",
            service_metrics.time() - service_metrics._PRODUCER_FRESHNESS_SEC - 1,
        )
        monkeypatch.setattr(service_metrics, "pair_last_tick_ts", _fresh_ticks(30))

        assert service_metrics.ingest_readiness() is False

    def test_readiness_true_in_grace_when_all_pairs_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fresh WS heartbeat still keeps readiness true during first-tick grace window."""
        monkeypatch.setattr(service_metrics, "startup_mode", "warmup")
        monkeypatch.setattr(service_metrics, "ingest_ready", True)
        monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
        monkeypatch.setattr(service_metrics, "producer_present", True)
        monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", service_metrics.time())
        stale_ts = service_metrics.time() - service_metrics._PRODUCER_FRESHNESS_SEC - 1
        monkeypatch.setattr(
            service_metrics,
            "pair_last_tick_ts",
            {
                "EURUSD": stale_ts,
                "GBPUSD": stale_ts,
            },
        )

        assert service_metrics.ingest_readiness() is True

    def test_readiness_false_when_bootstrap_failed_even_if_runtime_metrics_are_healthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(service_metrics, "startup_mode", "failed_no_cache")
        monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
        monkeypatch.setattr(service_metrics, "producer_present", True)
        monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", service_metrics.time())
        monkeypatch.setattr(service_metrics, "pair_last_tick_ts", _fresh_ticks(30))

        assert service_metrics.ingest_readiness() is False
        snapshot = service_metrics.build_runtime_snapshot(ws_connected=True)
        assert snapshot["ingest_state"] == "NOT_READY"
        assert snapshot["blocked_by"] == ["startup_not_bootstrapped"]


class TestHasStaleCacheFunction:
    """has_stale_cache() should correctly detect cached candle keys."""

    @pytest.mark.asyncio
    async def test_returns_true_when_cache_key_found(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[(0, ["wolf15:candle_history:EURUSD:H1"])])
        mock_redis.llen = AsyncMock(return_value=50)

        result = await warmup_bootstrap.has_stale_cache(mock_redis)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_keys(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[(0, [])])

        result = await warmup_bootstrap.has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_key_empty(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[(0, ["wolf15:candle_history:EURUSD:H1"])])
        mock_redis.llen = AsyncMock(return_value=0)

        result = await warmup_bootstrap.has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_scan_exception(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("redis down"))

        result = await warmup_bootstrap.has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_iterates_multiple_scan_pages(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[
                (42, []),
                (0, ["wolf15:candle_history:GBPUSD:H4"]),
            ]
        )
        mock_redis.llen = AsyncMock(return_value=10)

        result = await warmup_bootstrap.has_stale_cache(mock_redis)
        assert result is True


class TestWarmupCircuitBreakerOnModule:
    """warmup_bootstrap should expose the module-level circuit breaker contract."""

    def test_warmup_circuit_exists(self) -> None:
        assert isinstance(warmup_bootstrap.warmup_circuit, CircuitBreaker)

    def test_warmup_circuit_starts_closed(self) -> None:
        assert warmup_bootstrap.warmup_circuit.state is CircuitState.CLOSED
