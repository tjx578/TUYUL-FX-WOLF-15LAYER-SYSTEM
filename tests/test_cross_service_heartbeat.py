"""Tests for cross-service heartbeat validation (ARCH-GAP-05).

Covers:
- HEARTBEAT_ORCHESTRATOR key registration in classifier config
- CrossServiceHeartbeatValidator: async and sync variants
- Orchestrator freshness check via ORCHESTRATOR_STATE key
- Orchestrator writes dedicated heartbeat key via publish_state
- API /readyz includes orchestrator heartbeat gate
- Worker orchestrator health check flag logic
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 1. HEARTBEAT_ORCHESTRATOR key exists in redis_keys ──────────────────────


def test_heartbeat_orchestrator_key_defined():
    from core.redis_keys import HEARTBEAT_ORCHESTRATOR

    assert "heartbeat:orchestrator" in HEARTBEAT_ORCHESTRATOR


# ── 2. Orchestrator in SERVICE_HEARTBEAT_CONFIG ─────────────────────────────


def test_orchestrator_in_heartbeat_config():
    from state.heartbeat_classifier import SERVICE_HEARTBEAT_CONFIG

    assert "orchestrator" in SERVICE_HEARTBEAT_CONFIG
    key, max_age = SERVICE_HEARTBEAT_CONFIG["orchestrator"]
    assert "heartbeat:orchestrator" in key
    assert max_age > 0


# ── 3. classify_heartbeat: orchestrator alive / stale / missing ─────────────


def test_classify_orchestrator_alive():
    import orjson

    from state.heartbeat_classifier import HeartbeatState, classify_heartbeat

    now = time.time()
    raw = orjson.dumps({"producer": "wolf15-orchestrator", "ts": now})
    status = classify_heartbeat(raw, 90.0, service="orchestrator", now_ts=now)
    assert status.state == HeartbeatState.ALIVE
    assert status.age_seconds == 0.0
    assert status.producer == "wolf15-orchestrator"


def test_classify_orchestrator_stale():
    import orjson

    from state.heartbeat_classifier import HeartbeatState, classify_heartbeat

    now = time.time()
    raw = orjson.dumps({"producer": "wolf15-orchestrator", "ts": now - 200})
    status = classify_heartbeat(raw, 90.0, service="orchestrator", now_ts=now)
    assert status.state == HeartbeatState.STALE
    assert status.age_seconds is not None
    assert status.age_seconds >= 200.0


def test_classify_orchestrator_missing():
    from state.heartbeat_classifier import HeartbeatState, classify_heartbeat

    status = classify_heartbeat(None, 90.0, service="orchestrator")
    assert status.state == HeartbeatState.MISSING


# ── 4. validate_peer_health async ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_peer_health_all_alive():
    import orjson

    from state.cross_service_validator import PeerHealth, validate_peer_health

    now = time.time()
    payloads = {
        "wolf15:heartbeat:engine": orjson.dumps({"producer": "engine", "ts": now}),
        "wolf15:heartbeat:orchestrator": orjson.dumps({"producer": "orchestrator", "ts": now}),
    }
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=lambda k: payloads.get(k))

    summary = await validate_peer_health(redis_mock, ("engine", "orchestrator"))
    assert summary.health == PeerHealth.HEALTHY
    assert summary.all_alive is True
    assert len(summary.stale_peers) == 0
    assert len(summary.missing_peers) == 0


@pytest.mark.asyncio
async def test_validate_peer_health_orchestrator_missing():
    import orjson

    from state.cross_service_validator import PeerHealth, validate_peer_health

    now = time.time()
    payloads = {
        "wolf15:heartbeat:engine": orjson.dumps({"producer": "engine", "ts": now}),
    }
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=lambda k: payloads.get(k))

    summary = await validate_peer_health(redis_mock, ("engine", "orchestrator"))
    assert summary.health == PeerHealth.UNHEALTHY
    assert "orchestrator" in summary.missing_peers


@pytest.mark.asyncio
async def test_validate_peer_health_orchestrator_stale():
    import orjson

    from state.cross_service_validator import PeerHealth, validate_peer_health

    now = time.time()
    payloads = {
        "wolf15:heartbeat:engine": orjson.dumps({"producer": "engine", "ts": now}),
        "wolf15:heartbeat:orchestrator": orjson.dumps({"producer": "orchestrator", "ts": now - 200}),
    }
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=lambda k: payloads.get(k))

    summary = await validate_peer_health(redis_mock, ("engine", "orchestrator"))
    assert summary.health == PeerHealth.DEGRADED
    assert "orchestrator" in summary.stale_peers


# ── 5. validate_peer_health_sync ───────────────────────────────────────────


def test_validate_peer_health_sync_all_alive():
    import orjson

    from state.cross_service_validator import PeerHealth, validate_peer_health_sync

    now = time.time()
    payloads: dict[str, bytes | None] = {
        "wolf15:heartbeat:engine": orjson.dumps({"producer": "engine", "ts": now}),
        "wolf15:heartbeat:orchestrator": orjson.dumps({"producer": "orchestrator", "ts": now}),
    }
    redis_mock = MagicMock()
    redis_mock.get = MagicMock(side_effect=lambda k: payloads.get(k))

    summary = validate_peer_health_sync(redis_mock, ("engine", "orchestrator"), now_ts=now)
    assert summary.health == PeerHealth.HEALTHY
    assert summary.all_alive is True


def test_validate_peer_health_sync_missing():
    from state.cross_service_validator import PeerHealth, validate_peer_health_sync

    redis_mock = MagicMock()
    redis_mock.get = MagicMock(return_value=None)

    summary = validate_peer_health_sync(redis_mock, ("orchestrator",))
    assert summary.health == PeerHealth.UNHEALTHY
    assert "orchestrator" in summary.missing_peers


def test_validate_peer_health_sync_redis_error():
    from state.cross_service_validator import PeerHealth, validate_peer_health_sync

    redis_mock = MagicMock()
    redis_mock.get = MagicMock(side_effect=ConnectionError("Redis down"))

    summary = validate_peer_health_sync(redis_mock, ("orchestrator",))
    assert summary.health == PeerHealth.UNHEALTHY
    assert "orchestrator" in summary.missing_peers


# ── 6. check_orchestrator_freshness ────────────────────────────────────────


def test_orchestrator_freshness_fresh():
    from state.cross_service_validator import check_orchestrator_freshness

    now = time.time()
    state = json.dumps({"timestamp": int(now), "mode": "NORMAL"})
    redis_mock = MagicMock()
    redis_mock.get = MagicMock(return_value=state)

    is_fresh, age = check_orchestrator_freshness(redis_mock)
    assert is_fresh is True
    assert age is not None
    assert age < 5.0


def test_orchestrator_freshness_stale():
    from state.cross_service_validator import check_orchestrator_freshness

    old_ts = time.time() - 300
    state = json.dumps({"timestamp": int(old_ts), "mode": "NORMAL"})
    redis_mock = MagicMock()
    redis_mock.get = MagicMock(return_value=state)

    is_fresh, age = check_orchestrator_freshness(redis_mock, max_age_sec=120)
    assert is_fresh is False
    assert age is not None
    assert age >= 290.0


def test_orchestrator_freshness_missing():
    from state.cross_service_validator import check_orchestrator_freshness

    redis_mock = MagicMock()
    redis_mock.get = MagicMock(return_value=None)

    is_fresh, age = check_orchestrator_freshness(redis_mock)
    assert is_fresh is False
    assert age is None


def test_orchestrator_freshness_malformed():
    from state.cross_service_validator import check_orchestrator_freshness

    redis_mock = MagicMock()
    redis_mock.get = MagicMock(return_value="not-valid-json{{{")

    is_fresh, age = check_orchestrator_freshness(redis_mock)
    assert is_fresh is False
    assert age is None


# ── 7. Orchestrator publish_state writes HEARTBEAT_ORCHESTRATOR key ────────


def test_orchestrator_publishes_heartbeat_key():
    """StateManager.publish_state writes the dedicated HEARTBEAT_ORCHESTRATOR key."""
    from services.orchestrator.state_manager import StateManager

    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.pubsub.return_value = MagicMock()

    sm = StateManager(redis_client=mock_redis)
    sm.publish_state("HEARTBEAT")

    # The pipeline should have 3 operations: publish + set state + set heartbeat
    assert mock_pipe.set.call_count == 2
    set_calls = mock_pipe.set.call_args_list

    # Second set call should be the dedicated heartbeat key
    heartbeat_key = set_calls[1][0][0]
    assert "heartbeat:orchestrator" in heartbeat_key

    heartbeat_payload = json.loads(set_calls[1][0][1])
    assert "ts" in heartbeat_payload
    assert heartbeat_payload["producer"] == "wolf15-orchestrator"

    mock_pipe.execute.assert_called_once()


# ── 8. PeerHealthSummary.to_dict ───────────────────────────────────────────


def test_peer_health_summary_to_dict():
    from state.cross_service_validator import PeerHealth, PeerHealthSummary
    from state.heartbeat_classifier import HeartbeatState, HeartbeatStatus

    peers = {
        "engine": HeartbeatStatus(
            service="engine",
            state=HeartbeatState.ALIVE,
            age_seconds=5.0,
            producer="engine",
            last_ts=1.0,
        ),
        "orchestrator": HeartbeatStatus(
            service="orchestrator",
            state=HeartbeatState.STALE,
            age_seconds=200.0,
            producer="orch",
            last_ts=1.0,
        ),
    }
    summary = PeerHealthSummary(
        health=PeerHealth.DEGRADED,
        peers=peers,
        stale_peers=("orchestrator",),
        missing_peers=(),
    )
    d = summary.to_dict()
    assert d["health"] == "DEGRADED"
    assert d["stale_peers"] == ["orchestrator"]
    assert d["peers"]["engine"]["state"] == "ALIVE"
    assert d["peers"]["orchestrator"]["state"] == "STALE"


# ── 9. Unknown peer name is skipped gracefully ─────────────────────────────


@pytest.mark.asyncio
async def test_validate_unknown_peer_skipped():
    from state.cross_service_validator import PeerHealth, validate_peer_health

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)

    summary = await validate_peer_health(redis_mock, ("nonexistent_service",))
    # Unknown peer is skipped — no entry in peers dict
    assert "nonexistent_service" not in summary.peers
    assert summary.health == PeerHealth.HEALTHY


# ── 10. Allocation worker rejects when orchestrator dead ───────────────────


@pytest.mark.asyncio
async def test_allocation_worker_rejects_when_orchestrator_dead():
    """When _orchestrator_alive is False, _handle_message should ACK and return early."""
    from allocation.async_worker import AsyncAllocationWorker

    worker = AsyncAllocationWorker()
    worker._orchestrator_alive = False

    redis_mock = AsyncMock()
    redis_mock.xack = AsyncMock()

    await worker._handle_message(redis_mock, "allocation:request", "1-0", {"signal_id": "test"})

    redis_mock.xack.assert_called_once_with("allocation:request", "alloc-group", "1-0")


# ── 11. Execution worker tracks orchestrator alive flag ────────────────────


@pytest.mark.asyncio
async def test_execution_worker_orchestrator_flag_transitions():
    """_check_orchestrator_health should toggle _orchestrator_alive flag."""
    import orjson

    from execution.async_worker import AsyncExecutionWorker

    worker = AsyncExecutionWorker()
    assert worker._orchestrator_alive is True

    # Simulate missing orchestrator heartbeat
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)

    await worker._check_orchestrator_health(redis_mock)
    assert worker._orchestrator_alive is False

    # Restore heartbeat
    now = time.time()
    redis_mock.get = AsyncMock(return_value=orjson.dumps({"producer": "orchestrator", "ts": now}))
    await worker._check_orchestrator_health(redis_mock)
    assert worker._orchestrator_alive is True


# ── 12. Engine already checks ingest heartbeat (verify existing) ───────────


def test_engine_check_ingest_heartbeat_exists():
    """Verify the engine's _check_ingest_heartbeat function exists and is callable."""
    from startup.analysis_loop import _check_ingest_heartbeat

    assert callable(_check_ingest_heartbeat)


# ── 13. read_all_heartbeats now includes orchestrator ──────────────────────


@pytest.mark.asyncio
async def test_read_all_heartbeats_includes_orchestrator():
    import orjson

    from state.heartbeat_classifier import read_all_heartbeats

    now = time.time()
    payloads: dict[str, bytes | None] = {}
    from state.heartbeat_classifier import SERVICE_HEARTBEAT_CONFIG

    for svc, (key, _) in SERVICE_HEARTBEAT_CONFIG.items():
        payloads[key] = orjson.dumps({"producer": svc, "ts": now})

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=lambda k: payloads.get(k))

    results = await read_all_heartbeats(redis_mock)
    assert "orchestrator" in results
    assert results["orchestrator"].state.value == "ALIVE"
