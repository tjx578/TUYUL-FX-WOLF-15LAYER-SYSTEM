"""Real loopback WebSocket load against production routes and authentication.

Runs its own subprocess with deterministic TEST_ONLY readers; never uses an
external URL or account. This verifies socket/route lifecycle, not live feeds,
Redis persistence, application worker startup or broker readiness.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import jwt
import pytest
import websockets

from scripts.ci.built_api_acceptance import environment

TOTAL_CONNECTIONS = 50
CHANNEL_EVENTS = {
    "prices": "price.snapshot",
    "trades": "trade.snapshot",
    "candles": "candle.snapshot",
    "risk": "risk.state",
    "equity": "equity.snapshot",
}
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def socket_server(tmp_path_factory):
    folder = tmp_path_factory.mktemp("ws-loopback")
    address_path = folder / "address.json"
    root = Path(__file__).resolve().parents[1]
    env = environment()
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONPATH"] = str(root)
    # Fixture-only signing key, never inherited host credentials.
    env["DASHBOARD_JWT_SECRET"] = "test-only-loopback-ws-jwt-key-at-least-32-characters"
    env["JWT_SECRET"] = env["DASHBOARD_JWT_SECRET"]
    env["WOLF15_FORENSIC_ARTIFACTS_PATH"] = str(folder / "forensics.jsonl")
    with (folder / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(root / "tests/fixtures/ws_load_app.py"), str(address_path)],
            cwd=folder,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, "socket fixture exited: " + (folder / "server.log").read_text()[-3000:]
                if address_path.exists():
                    address = json.loads(address_path.read_text())
                    base = f"http://127.0.0.1:{address['port']}"
                    try:
                        with urllib.request.urlopen(base + "/__test_only/ws-state", timeout=1) as response:
                            assert set(json.load(response)) == set(CHANNEL_EVENTS)
                        break
                    except OSError:
                        pass
                time.sleep(0.05)
            else:
                pytest.fail("loopback socket fixture startup timed out")
            yield base, env["DASHBOARD_JWT_SECRET"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                pytest.fail("loopback socket fixture did not stop within 10 seconds")


def _token(socket_server, *, scoped=True):
    payload = {"sub": "TEST_ONLY_SOCKET_READER", "role": "viewer", "exp": int(time.time()) + 120}
    if scoped:
        payload["account_id"] = "TEST_ONLY_SOCKET_ACCOUNT"
    return jwt.encode(payload, socket_server[1], algorithm="HS256")


def _url(socket_server, channel, token):
    return f"{socket_server[0].replace('http:', 'ws:')}/ws/{channel}?token={token}"


async def _assert_released(socket_server):
    def read_state():
        with urllib.request.urlopen(socket_server[0] + "/__test_only/ws-state", timeout=2) as response:
            return json.load(response)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = await asyncio.to_thread(read_state)
        if all(count == 0 for manager in state.values() for count in manager.values()):
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"connection state leaked after disconnect: {state}")


async def _receive_snapshot(ws, channel):
    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    assert event["event_type"] == CHANNEL_EVENTS[channel]
    assert event["event_version"] == "1.0"
    assert event["event_id"] and isinstance(event["payload"], dict)


@pytest.mark.asyncio
async def test_ws_load_50_connections(socket_server):
    """All 50 clients receive the correct snapshot and stay open together."""
    ready = asyncio.Queue()
    release = asyncio.Event()

    async def client(index):
        channel = list(CHANNEL_EVENTS)[index % len(CHANNEL_EVENTS)]
        async with websockets.connect(_url(socket_server, channel, _token(socket_server)), open_timeout=10) as ws:
            await _receive_snapshot(ws, channel)
            await ready.put(channel)
            await release.wait()
            # Ping/pong after the hold rejects upgrade-only false positives.
            pong = await ws.ping()
            await asyncio.wait_for(pong, timeout=3)

    tasks = [asyncio.create_task(client(index)) for index in range(TOTAL_CONNECTIONS)]
    try:
        channels = [await asyncio.wait_for(ready.get(), timeout=10) for _ in tasks]
        assert all(channels.count(channel) == 10 for channel in CHANNEL_EVENTS)
        await asyncio.sleep(5)
        release.set()
        await asyncio.gather(*tasks)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    await _assert_released(socket_server)


@pytest.mark.asyncio
async def test_ws_channel_isolation(socket_server):
    """Each route authenticates and emits its own snapshot contract."""
    for channel in CHANNEL_EVENTS:
        async with websockets.connect(_url(socket_server, channel, _token(socket_server)), open_timeout=5) as ws:
            await _receive_snapshot(ws, channel)
    await _assert_released(socket_server)


@pytest.mark.asyncio
async def test_ws_rapid_connect_disconnect(socket_server):
    """All 20 churn cycles authenticate, emit and release manager resources."""
    for index in range(20):
        channel = list(CHANNEL_EVENTS)[index % len(CHANNEL_EVENTS)]
        async with websockets.connect(_url(socket_server, channel, _token(socket_server)), open_timeout=5) as ws:
            await _receive_snapshot(ws, channel)
    await _assert_released(socket_server)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_kind", ["invalid", "unscoped"])
async def test_ws_load_fixture_does_not_bypass_auth(socket_server, token_kind):
    token = "TEST_ONLY_INVALID" if token_kind == "invalid" else _token(socket_server, scoped=False)
    for channel in CHANNEL_EVENTS:
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as rejected:
            async with websockets.connect(_url(socket_server, channel, token), open_timeout=5):
                pytest.fail("unauthorized socket was accepted")
        assert rejected.value.status_code == 403
    await _assert_released(socket_server)
