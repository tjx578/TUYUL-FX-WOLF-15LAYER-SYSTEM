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


def test_actual_mode_writer_expiry_takeover_rejects_stale_all_state_writes(store):
    client, prefix = store
    first = sm.StateManager(redis_client=client)
    first.set_mode(ExecutionMode.KILL_SWITCH, "disposable-first")
    first._sync_kill_switch(ExecutionMode.KILL_SWITCH)
    first.publish_state("TEST_ONLY")
    assert first._mode_owner.is_current()
    contender = sm.StateManager(redis_client=client)
    with pytest.raises(ModeOwnerUnavailableError):
        contender.publish_state("TEST_ONLY_DUPLICATE")
    deadline = time.monotonic() + 3
    while client.exists(first._mode_owner.key) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not client.exists(first._mode_owner.key)
    assert first._mode_owner.is_current() is False
    successor = sm.StateManager(redis_client=client)
    successor._mode_owner.ttl_ms = 5000
    successor.set_mode(ExecutionMode.KILL_SWITCH, "disposable-successor")
    successor._sync_kill_switch(ExecutionMode.KILL_SWITCH)
    successor.publish_state("TEST_ONLY_SUCCESSOR")
    keys = [prefix + "state", prefix + "heartbeat", prefix + "kill", successor._mode_owner.key]
    before = client.mget(keys)
    assert successor._mode_owner.is_current()
    assert first._mode_owner.is_current() is False
    with pytest.raises(ModeOwnerUnavailableError):
        first._sync_kill_switch(ExecutionMode.NORMAL)
    with pytest.raises(ModeOwnerUnavailableError):
        first.publish_state("STALE_SHUTDOWN")
    with pytest.raises(ModeOwnerUnavailableError):
        first._mode_owner.renew()
    first.close()
    assert client.mget(keys) == before
    successor.close()
    assert not client.exists(successor._mode_owner.key)


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
