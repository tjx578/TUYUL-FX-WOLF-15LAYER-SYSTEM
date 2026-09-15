"""Real Redis C02 acceptance. Unique disposable /15 keys; never FLUSHDB."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import redis

from services.orchestrator import state_manager as sm
from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.mode_owner import ModeOwnerLease, ModeOwnerUnavailableError
from services.orchestrator.ownership import OwnershipLostError


@pytest.fixture
def store(monkeypatch):
    if os.environ.get("WOLF15_RUN_MODE_OWNER_REDIS") != "1":
        pytest.skip("requires explicitly enabled disposable mode-owner Redis")
    url = os.environ["WOLF15_MODE_OWNER_TEST_REDIS_URL"]
    parsed = urlsplit(url)
    assert parsed.scheme == "redis" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path == "/15" and not parsed.username and not parsed.password
    assert not parsed.query and not parsed.fragment
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    assert client.ping(), "required Redis acceptance must fail, not skip, when unavailable"
    prefix = "wolf15:disposable:mode-owner:" + uuid4().hex + ":"
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", prefix + "state")
    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", prefix + "channel")
    monkeypatch.setenv("ORCHESTRATOR_OWNER_LEASE_MS", "500")
    monkeypatch.setenv("ORCHESTRATOR_LEASE_KEY", prefix + "runtime-lease")
    monkeypatch.setenv("ORCHESTRATOR_FENCE_COUNTER_KEY", prefix + "runtime-generation")
    monkeypatch.setenv("ORCHESTRATOR_LEASE_TTL_SEC", "3")
    monkeypatch.setenv("ORCHESTRATOR_LEASE_RENEW_INTERVAL_SEC", "1")
    monkeypatch.setattr(sm, "KILL_SWITCH", prefix + "kill")
    monkeypatch.setattr(sm, "HEARTBEAT_ORCHESTRATOR", prefix + "heartbeat")
    try:
        yield client, prefix
    finally:
        keys = list(client.scan_iter(match=prefix + "*"))
        if keys:
            assert all(key.startswith(prefix) for key in keys)
            client.delete(*keys)
        client.close()


def test_atomic_duplicate_owner_race_has_one_winner(store):
    client, prefix = store
    owners = [ModeOwnerLease(client, key=prefix + "lease", ttl_ms=5000) for _ in range(8)]

    def claim(owner):
        try:
            owner.acquire()
            return True
        except ModeOwnerUnavailableError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, owners))
    assert sum(results) == 1
    for owner, won in zip(owners, results, strict=True):
        if not won:
            with pytest.raises(ModeOwnerUnavailableError):
                owner.write([(prefix + "state", "stale")])
    assert client.get(prefix + "state") is None


@pytest.mark.parametrize("stale_operation", ["kill", "state", "renew", "release"])
def test_actual_mode_writer_expiry_takeover_rejects_stale_all_state_writes(store, monkeypatch, stale_operation):
    client, prefix = store
    lease_key = prefix + "runtime-lease"
    first = sm.StateManager(redis_client=client)
    assert first._ownership.acquire()
    first_identity = first._ownership.identity
    assert first_identity is not None
    first.set_mode(ExecutionMode.KILL_SWITCH, "disposable-first")
    first._sync_kill_switch(ExecutionMode.KILL_SWITCH)
    first.publish_state("TEST_ONLY")
    assert client.get(lease_key) == first_identity.wire_value
    contender = sm.StateManager(redis_client=client)
    assert contender._ownership.acquire() is False
    with pytest.raises(OwnershipLostError):
        contender.publish_state("TEST_ONLY_DUPLICATE")
    deadline = time.monotonic() + 5
    while client.exists(lease_key) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not client.exists(lease_key)
    monkeypatch.setenv("ORCHESTRATOR_LEASE_TTL_SEC", "15")
    successor = sm.StateManager(redis_client=client)
    assert successor._ownership.acquire()
    successor_identity = successor._ownership.identity
    assert successor_identity is not None and successor_identity.generation > first_identity.generation
    successor.set_mode(ExecutionMode.KILL_SWITCH, "disposable-successor")
    successor._sync_kill_switch(ExecutionMode.KILL_SWITCH)
    successor.publish_state("TEST_ONLY_SUCCESSOR")
    keys = [prefix + "state", prefix + "heartbeat", prefix + "kill", lease_key, prefix + "runtime-generation"]
    before = client.mget(keys)
    assert client.get(lease_key) == successor_identity.wire_value
    # Exercise each Lua stale-token gate first, before local invalidation of
    # the obsolete identity can short-circuit subsequent calls.
    if stale_operation == "kill":
        with pytest.raises(OwnershipLostError):
            first._sync_kill_switch(ExecutionMode.NORMAL)
    elif stale_operation == "state":
        with pytest.raises(OwnershipLostError):
            first.publish_state("STALE_SHUTDOWN")
    elif stale_operation == "renew":
        assert first._ownership.renew() is False
    else:
        assert first._ownership.release() is False
    with pytest.raises(OwnershipLostError):
        first._sync_kill_switch(ExecutionMode.NORMAL)
    with pytest.raises(OwnershipLostError):
        first.publish_state("STALE_SHUTDOWN")
    assert first._ownership.renew() is False
    assert first._ownership.release() is False
    first.close()
    assert client.mget(keys) == before
    successor.close()
    assert successor._ownership.release() is True
    assert not client.exists(lease_key)


def test_backend_unavailable_does_not_fall_back_or_acquire_authority(store):
    client, prefix = store
    unavailable = redis.Redis(host="127.0.0.1", port=1, db=15, socket_timeout=0.1, socket_connect_timeout=0.1)
    owner = ModeOwnerLease(unavailable, key=prefix + "lease")
    try:
        with pytest.raises(ModeOwnerUnavailableError, match="STORE_UNAVAILABLE"):
            owner.acquire()
        with pytest.raises(ModeOwnerUnavailableError, match="REACQUIRE_FORBIDDEN"):
            owner.acquire()
        assert client.get(prefix + "lease") is None
    finally:
        unavailable.close()


@pytest.mark.asyncio
async def test_served_health_probe_rejects_expired_mode_owner(store):
    import asyncio

    from core.health_probe import HealthProbe

    client, prefix = store
    owner = ModeOwnerLease(client, key=prefix + "lease", ttl_ms=500)
    owner.acquire()
    probe = HealthProbe(port=0, service_name="disposable-orchestrator", readiness_check=owner.is_current)
    server = await asyncio.start_server(probe._handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def served_status():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /readyz HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        result = await reader.read()
        writer.close()
        await writer.wait_closed()
        return result.split(b"\r\n", 1)[0]

    try:
        assert b"200 OK" in await served_status()
        deadline = time.monotonic() + 3
        while client.exists(owner.key) and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert not client.exists(owner.key)
        assert b"503 Service Unavailable" in await served_status()
    finally:
        server.close()
        await server.wait_closed()
        with pytest.raises(ModeOwnerUnavailableError):
            owner.release()
