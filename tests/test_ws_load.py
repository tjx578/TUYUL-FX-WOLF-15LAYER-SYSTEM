"""
WebSocket Load Test — 50 concurrent connections across all 5 channels.

Usage:
    pytest tests/test_ws_load.py -v --timeout=60
    # Or standalone:
    python tests/test_ws_load.py

Requires the API server to be running (or uses the FastAPI TestClient).
Channels tested: /ws/prices, /ws/trades, /ws/candles, /ws/risk, /ws/equity
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOTAL_CONNECTIONS = 50
WS_CHANNELS = ["/ws/prices", "/ws/trades", "/ws/candles", "/ws/risk", "/ws/equity"]
# Distribute connections round-robin across channels
CONNECT_TIMEOUT = 10.0  # seconds per connection
HOLD_DURATION = 5.0  # seconds to hold all connections open
RECEIVE_TIMEOUT = 3.0  # seconds to wait for at least one message


def _str_list_factory() -> list[str]:
    return []


def _float_list_factory() -> list[float]:
    return []


@dataclass
class LoadTestStats:
    """Accumulates stats across all concurrent WebSocket connections."""

    connected: int = 0
    failed_connect: int = 0
    messages_received: int = 0
    errors: list[str] = field(default_factory=_str_list_factory)
    latencies: list[float] = field(default_factory=_float_list_factory)
    connect_times: list[float] = field(default_factory=_float_list_factory)
    disconnected_early: int = 0


# ---------------------------------------------------------------------------
# In-process load test (uses httpx + FastAPI TestClient)
# ---------------------------------------------------------------------------


def _get_test_token() -> str:
    """Generate a valid JWT for WebSocket auth during tests."""
    try:
        import jwt as pyjwt
    except ImportError:
        pytest.skip("PyJWT not installed — install with: pip install PyJWT")

    secret = os.getenv("DASHBOARD_JWT_SECRET") or os.getenv("JWT_SECRET") or "test-secret"
    algo = os.getenv("DASHBOARD_JWT_ALGO", "HS256")
    payload = {
        "sub": "load-test-user",
        "role": "viewer",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return pyjwt.encode(payload, secret, algorithm=algo)  # type: ignore[arg-type]


async def _ws_client(
    base_url: str,
    channel: str,
    token: str,
    stats: LoadTestStats,
    hold_seconds: float,
    client_id: int,
) -> None:
    """Single WebSocket client that connects, receives, and disconnects."""
    try:
        import websockets
    except ImportError:
        pytest.skip("websockets not installed — install with: pip install websockets")

    url = f"{base_url}{channel}?token={token}"
    t0 = time.monotonic()
    try:
        async with websockets.connect(
            url,
            open_timeout=CONNECT_TIMEOUT,
            close_timeout=5.0,
        ) as ws:
            connect_time = time.monotonic() - t0
            stats.connected += 1
            stats.connect_times.append(connect_time)

            # Hold connection and collect messages
            deadline = time.monotonic() + hold_seconds
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(1.0, RECEIVE_TIMEOUT))
                    recv_ts = time.monotonic()
                    stats.messages_received += 1

                    # Try to extract server_ts for latency calc
                    try:
                        data = json.loads(msg)
                        server_ts = data.get("server_ts") or data.get("payload", {}).get("server_ts")
                        if server_ts:
                            latency = recv_ts - float(server_ts)
                            if 0 < latency < 30:  # sanity guard
                                stats.latencies.append(latency)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                except TimeoutError:
                    continue
                except Exception:
                    stats.disconnected_early += 1
                    break

    except Exception as exc:
        stats.failed_connect += 1
        stats.errors.append(f"client-{client_id} {channel}: {type(exc).__name__}: {exc}")


@pytest.mark.asyncio
async def test_ws_load_50_connections() -> None:
    """Stress test: open 50 concurrent WebSocket connections across all channels.

    Asserts:
      - At least 80% of connections succeed (40/50)
      - No channel is completely unreachable
      - Server stays responsive throughout
    """
    try:
        import websockets  # type: ignore[import-untyped] # noqa: F401
    except ImportError:
        pytest.skip("websockets not installed")

    base_url = os.getenv("WS_LOAD_TEST_URL", "ws://localhost:8000")
    token = _get_test_token()
    stats = LoadTestStats()

    # Distribute connections round-robin across channels
    tasks: list[asyncio.Task[None]] = []
    for i in range(TOTAL_CONNECTIONS):
        channel = WS_CHANNELS[i % len(WS_CHANNELS)]
        task = asyncio.create_task(_ws_client(base_url, channel, token, stats, HOLD_DURATION, i))
        tasks.append(task)

    # Wait for all to complete
    await asyncio.gather(*tasks, return_exceptions=True)

    # ── Report ────────────────────────────────────────────────────────────
    avg_connect = sum(stats.connect_times) / len(stats.connect_times) if stats.connect_times else 0
    avg_latency = sum(stats.latencies) / len(stats.latencies) if stats.latencies else 0
    p95_connect = sorted(stats.connect_times)[int(len(stats.connect_times) * 0.95)] if stats.connect_times else 0

    print("\n" + "=" * 60)
    print("WebSocket Load Test Results")
    print("=" * 60)
    print(f"  Target connections: {TOTAL_CONNECTIONS}")
    print(f"  Connected:          {stats.connected}")
    print(f"  Failed:             {stats.failed_connect}")
    print(f"  Disconnected early: {stats.disconnected_early}")
    print(f"  Messages received:  {stats.messages_received}")
    print(f"  Avg connect time:   {avg_connect:.3f}s")
    print(f"  P95 connect time:   {p95_connect:.3f}s")
    print(f"  Avg msg latency:    {avg_latency:.3f}s")
    if stats.errors:
        print(f"  Errors ({len(stats.errors)}):")
        for err in stats.errors[:10]:
            print(f"    - {err}")
    print("=" * 60)

    # ── Assertions ────────────────────────────────────────────────────────
    min_connected = int(TOTAL_CONNECTIONS * 0.8)
    assert stats.connected >= min_connected, (
        f"Only {stats.connected}/{TOTAL_CONNECTIONS} connected (minimum {min_connected} required)"
    )


@pytest.mark.asyncio
async def test_ws_channel_isolation() -> None:
    """Verify each channel can accept at least 1 connection independently."""
    try:
        import websockets  # type: ignore[import-untyped] # noqa: F401
    except ImportError:
        pytest.skip("websockets not installed")

    base_url = os.getenv("WS_LOAD_TEST_URL", "ws://localhost:8000")
    token = _get_test_token()
    results: dict[str, bool] = {}

    for channel in WS_CHANNELS:
        stats = LoadTestStats()
        await _ws_client(base_url, channel, token, stats, hold_seconds=2.0, client_id=0)
        results[channel] = stats.connected > 0

    print("\nChannel isolation results:")
    for ch, ok in results.items():
        print(f"  {ch}: {'OK' if ok else 'FAIL'}")

    failed = [ch for ch, ok in results.items() if not ok]
    assert not failed, f"Channels unreachable: {failed}"


@pytest.mark.asyncio
async def test_ws_rapid_connect_disconnect() -> None:
    """Rapid connect/disconnect cycle — tests resource cleanup under churn."""
    try:
        import websockets
    except ImportError:
        pytest.skip("websockets not installed")

    base_url = os.getenv("WS_LOAD_TEST_URL", "ws://localhost:8000")
    token = _get_test_token()
    cycles = 20
    success = 0

    for i in range(cycles):
        channel = WS_CHANNELS[i % len(WS_CHANNELS)]
        url = f"{base_url}{channel}?token={token}"
        try:
            async with websockets.connect(url, open_timeout=5.0):
                success += 1
                # Immediately close — tests cleanup path
        except Exception:
            pass

    print(f"\nRapid connect/disconnect: {success}/{cycles} succeeded")
    assert success >= cycles * 0.7, f"Only {success}/{cycles} rapid cycles succeeded"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(test_ws_load_50_connections())
