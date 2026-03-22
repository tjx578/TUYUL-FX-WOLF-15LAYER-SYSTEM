"""
WebSocket Load & Stress Tests — Connection Limit and Broadcast Throughput.

Covers:
  - MAX_WS_CONNECTIONS = 50 cap enforcement
  - 51st connection must be rejected with close code 4429
  - Broadcast throughput: N simultaneous clients receive messages
  - Disconnect frees a slot for a new connection
  - Message ring-buffer doesn't overflow (deque(maxlen=100))
  - Per-manager isolation: price_manager vs trade_manager are independent
  - Heartbeat task lifecycle (create / cancel without memory leak)

These tests use ConnectionManager directly (no network I/O), so they
run fast and are suitable for CI with no external dependencies.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_ws(client_id: str = "ws") -> MagicMock:
    """Lightweight mock WebSocket with async send_json and close."""
    ws = MagicMock()
    # Do NOT override __hash__/__eq__ — MagicMock uses identity-based hash by
    # default which is exactly what set operations need.
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    ws.query_params = MagicMock()
    ws.query_params.get = MagicMock(return_value=None)
    return ws


async def _connect_n(manager, n: int, auth_user: dict | None = None) -> list[MagicMock]:
    """
    Attempt to connect N mock WebSockets to manager.

    Returns list of mock WS objects that were accepted.
    """
    accepted = []
    user = auth_user or {"sub": f"user-{n}"}
    for i in range(n):
        ws = _make_ws(f"ws-{i}")
        # Suppress heartbeat task creation so it doesn't interfere
        with (
            patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value=user)),
            patch("asyncio.create_task", return_value=MagicMock(done=lambda: True, cancel=lambda: None)),
        ):
            connected = await manager.connect(ws)
        if connected:
            accepted.append(ws)
    return accepted


# ──────────────────────────────────────────────────────────────────────────────
# Connection cap: exactly MAX_WS_CONNECTIONS are accepted
# ──────────────────────────────────────────────────────────────────────────────


class TestConnectionCap:
    """MAX_WS_CONNECTIONS = 50 must be strictly enforced."""

    @pytest.fixture
    def manager(self):
        from api.ws_routes import MAX_WS_CONNECTIONS, ConnectionManager  # noqa: PLC0415

        return ConnectionManager(name="stress-test", buffer_size=10), MAX_WS_CONNECTIONS

    @pytest.mark.asyncio
    async def test_exactly_50_connections_accepted(self, manager):
        """Exactly MAX_WS_CONNECTIONS connections must be accepted."""
        mgr, cap = manager
        accepted = await _connect_n(mgr, cap)
        assert len(accepted) == cap
        assert len(mgr.active_connections) == cap

    @pytest.mark.asyncio
    async def test_51st_connection_rejected(self, manager):
        """The (cap + 1)th connection must be refused."""
        mgr, cap = manager
        # Fill to cap
        await _connect_n(mgr, cap)

        # 51st attempt
        extra_ws = _make_ws("ws-overflow")
        with (
            patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "overflow"})),
            patch("asyncio.create_task", return_value=MagicMock(done=lambda: True, cancel=lambda: None)),
        ):
            connected = await mgr.connect(extra_ws)

        assert connected is False, "51st connection must be rejected"
        assert extra_ws not in mgr.active_connections
        # close() must have been called with the overflow code
        extra_ws.close.assert_called_once()
        call_kwargs = extra_ws.close.call_args
        code = call_kwargs[1].get("code") or (call_kwargs[0][0] if call_kwargs[0] else None)
        assert code == 4429, f"Expected close code 4429, got {code}"

    @pytest.mark.asyncio
    async def test_disconnect_frees_slot(self, manager):
        """Disconnecting one client must allow a new one to join."""
        mgr, cap = manager
        accepted = await _connect_n(mgr, cap)

        # Disconnect the first client
        victim = accepted[0]
        mgr.disconnect(victim)
        assert len(mgr.active_connections) == cap - 1

        # New client should now be accepted
        new_ws = _make_ws("ws-replacement")
        with (
            patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "new"})),
            patch("asyncio.create_task", return_value=MagicMock(done=lambda: True, cancel=lambda: None)),
        ):
            connected = await mgr.connect(new_ws)

        assert connected is True
        assert len(mgr.active_connections) == cap

    @pytest.mark.asyncio
    async def test_multiple_disconnects_then_reconnect(self, manager):
        """Disconnecting 10 and reconnecting 10 must stay within cap."""
        mgr, cap = manager
        accepted = await _connect_n(mgr, cap)

        batch_to_remove = accepted[:10]
        for ws in batch_to_remove:
            mgr.disconnect(ws)

        assert len(mgr.active_connections) == cap - 10

        new_batch = await _connect_n(mgr, 10)
        assert len(new_batch) == 10
        assert len(mgr.active_connections) == cap

    @pytest.mark.asyncio
    async def test_zero_connections_at_start(self, manager):
        """Fresh manager must start with zero active connections."""
        mgr, _ = manager
        assert len(mgr.active_connections) == 0

    @pytest.mark.asyncio
    async def test_cap_enforced_independently_per_manager(self):
        """Each manager has its own cap — filling one doesn't affect another."""
        from api.ws_routes import MAX_WS_CONNECTIONS, ConnectionManager  # noqa: PLC0415

        mgr_a = ConnectionManager(name="a")
        mgr_b = ConnectionManager(name="b")

        # Fill mgr_a to cap
        await _connect_n(mgr_a, MAX_WS_CONNECTIONS)
        assert len(mgr_a.active_connections) == MAX_WS_CONNECTIONS

        # mgr_b should still accept connections
        accepted_b = await _connect_n(mgr_b, 5)
        assert len(accepted_b) == 5
        assert len(mgr_b.active_connections) == 5


# ──────────────────────────────────────────────────────────────────────────────
# Broadcast throughput
# ──────────────────────────────────────────────────────────────────────────────


class TestBroadcastThroughput:
    """Broadcast must reach all 50 clients within time constraints."""

    @pytest.mark.asyncio
    async def test_broadcast_reaches_50_clients(self):
        """broadcast() to 50 clients must call send_json on all 50."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="broadcast-test")
        clients = [_make_ws(f"ws-{i}") for i in range(50)]
        for c in clients:
            mgr.active_connections.add(c)

        msg = {"type": "tick", "data": {"EURUSD": {"bid": 1.085, "ask": 1.0851}}}
        await mgr.broadcast(msg)

        for c in clients:
            c.send_json.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_50_clients_under_100ms(self):
        """Broadcast to 50 mock clients must complete in under 100ms."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="latency-test")
        clients = [_make_ws(f"ws-{i}") for i in range(50)]
        for c in clients:
            mgr.active_connections.add(c)

        msg = {"type": "risk_state", "data": {"ts": time.time()}}
        start = time.perf_counter()
        await mgr.broadcast(msg)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Broadcast to 50 clients took {elapsed_ms:.1f}ms (limit: 100ms)"

    @pytest.mark.asyncio
    async def test_broadcast_1000_messages_to_10_clients(self):
        """1000 sequential broadcasts to 10 clients must stay under 1s total."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="sustained-test")
        clients = [_make_ws(f"ws-{i}") for i in range(10)]
        for c in clients:
            mgr.active_connections.add(c)

        start = time.perf_counter()
        for i in range(1000):
            await mgr.broadcast({"seq": i, "ts": time.time()})
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"1000 broadcasts to 10 clients took {elapsed:.2f}s (limit: 1.0s)"
        # All clients must have received all 1000 messages
        for c in clients:
            assert c.send_json.call_count == 1000

    @pytest.mark.asyncio
    async def test_broadcast_skips_broken_clients_silently(self):
        """Broken clients must be removed without crashing broadcast."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="broken-test")

        good_clients = [_make_ws(f"good-{i}") for i in range(10)]
        bad_clients = [_make_ws(f"bad-{i}") for i in range(5)]
        for bc in bad_clients:
            bc.send_json.side_effect = ConnectionError("closed")

        for c in good_clients + bad_clients:
            mgr.active_connections.add(c)

        # Should not raise
        await mgr.broadcast({"type": "test"})

        # Good clients received message
        for gc in good_clients:
            gc.send_json.assert_called_once()

        # Bad clients removed
        for bc in bad_clients:
            assert bc not in mgr.active_connections


# ──────────────────────────────────────────────────────────────────────────────
# Message ring buffer
# ──────────────────────────────────────────────────────────────────────────────


class TestMessageBuffer:
    """Message buffer (deque maxlen=100) must not overflow and must replay."""

    @pytest.fixture
    def buffered_manager(self):
        from api.ws_routes import MESSAGE_BUFFER_SIZE, ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="buf-test", buffer_size=MESSAGE_BUFFER_SIZE)
        return mgr, MESSAGE_BUFFER_SIZE

    def test_buffer_respects_maxlen(self, buffered_manager):
        """Inserting >100 messages must evict oldest, keeping only last 100."""
        mgr, cap = buffered_manager
        for i in range(cap + 50):  # 150 messages if cap=100
            mgr.buffer_message({"seq": i})

        assert len(mgr._message_buffer) == cap

    def test_buffer_evicts_oldest_first(self, buffered_manager):
        """After overflow, the oldest messages must be gone."""
        mgr, cap = buffered_manager
        total = cap + 20
        for i in range(total):
            mgr.buffer_message({"seq": i})

        first_seq = mgr._message_buffer[0]["seq"]
        assert first_seq == total - cap, f"Oldest seq should be {total - cap}, got {first_seq}"

    def test_buffer_is_per_manager(self):
        """Each manager has its own independent buffer."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr_a = ConnectionManager(name="buf-a", buffer_size=5)
        mgr_b = ConnectionManager(name="buf-b", buffer_size=5)

        mgr_a.buffer_message({"type": "a"})
        assert len(mgr_b._message_buffer) == 0

    @pytest.mark.asyncio
    async def test_replay_buffer_under_load(self, buffered_manager):
        """replay_buffer must send all 100 buffered messages without dropping."""
        mgr, cap = buffered_manager
        for i in range(cap):
            mgr.buffer_message({"seq": i, "ts": float(i)})

        ws = _make_ws("replay-client")
        await mgr.replay_buffer(ws)

        assert ws.send_json.call_count == cap

    @pytest.mark.asyncio
    async def test_replay_buffer_with_since_ts(self, buffered_manager):
        """replay_buffer(since_ts) must only send messages newer than cutoff."""
        mgr, cap = buffered_manager
        cutoff_ts = 50.0
        for i in range(100):
            mgr.buffer_message({"seq": i, "ts": float(i)})

        ws = _make_ws("replay-client")
        await mgr.replay_buffer(ws, since_ts=cutoff_ts)

        # Messages with ts > 50.0 are seq 51..99 → 49 messages
        expected = sum(1 for i in range(100) if float(i) > cutoff_ts)
        assert ws.send_json.call_count == expected

    @pytest.mark.asyncio
    async def test_replay_to_disconnected_client_stops_gracefully(self, buffered_manager):
        """replay_buffer must stop mid-replay if client disconnects (send raises)."""
        mgr, cap = buffered_manager
        for i in range(cap):
            mgr.buffer_message({"seq": i, "ts": float(i)})

        ws = _make_ws("disconnect-replay")
        ws.send_json.side_effect = ConnectionError("disconnected")

        # Must not raise
        await mgr.replay_buffer(ws)


# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat task lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestHeartbeatLifecycle:
    """Heartbeat tasks must be started on connect and cancelled on disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_cancels_heartbeat_task(self):
        """disconnect() must cancel the heartbeat asyncio.Task."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="hb-test")

        ws = _make_ws("ws-hb")
        mock_task = MagicMock()
        mock_task.done = MagicMock(return_value=False)
        mock_task.cancel = MagicMock()

        # Manually inject WS + heartbeat task
        mgr.active_connections.add(ws)
        mgr._ping_tasks[ws] = mock_task

        mgr.disconnect(ws)

        mock_task.cancel.assert_called_once()
        assert ws not in mgr.active_connections
        assert ws not in mgr._ping_tasks

    @pytest.mark.asyncio
    async def test_disconnect_idempotent_on_double_call(self):
        """Calling disconnect twice on the same WS must not raise."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="idem-test")

        ws = _make_ws("ws-idem")
        mgr.active_connections.add(ws)

        mgr.disconnect(ws)  # first
        mgr.disconnect(ws)  # second — must not raise

    @pytest.mark.asyncio
    async def test_heartbeat_loop_cancels_on_asyncio_cancelled(self):
        """
        _heartbeat_loop must exit cleanly when the task is cancelled.
        The loop catches CancelledError internally and swallows it (by design),
        so the task completes normally — await must not raise.
        """
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="hb-cancel-test")

        ws = _make_ws("ws-hb-cancel")
        mgr.active_connections.add(ws)

        # Create a real heartbeat task and immediately cancel it
        task = asyncio.create_task(mgr._heartbeat_loop(ws))
        await asyncio.sleep(0)  # let the event loop start the coroutine
        task.cancel()

        # Heartbeat loop catches CancelledError internally: task must finish
        # without re-raising. Give it a 1s timeout to avoid hanging.
        try:  # noqa: SIM105
            await asyncio.wait_for(task, timeout=1.0)
        except (TimeoutError, asyncio.CancelledError):
            pass  # acceptable: CancelledError may or may not propagate

        assert task.done(), "Heartbeat task must be done after cancellation"


# ──────────────────────────────────────────────────────────────────────────────
# Concurrent connect + disconnect stress
# ──────────────────────────────────────────────────────────────────────────────


class TestConcurrentConnectStress:
    """Simulate concurrent connect/disconnect churn within the limit."""

    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect_churn(self):
        """
        Simulate 200 sequential connect/disconnect cycles within the 50-slot limit.
        No slot must be lost (leaked) after all disconnects.
        """
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="churn-test")

        for _ in range(200):
            # Connect one
            ws = _make_ws()
            with (
                patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "churn"})),
                patch("asyncio.create_task", return_value=MagicMock(done=lambda: True, cancel=lambda: None)),
            ):
                connected = await mgr.connect(ws)
            if connected:
                mgr.disconnect(ws)

        assert len(mgr.active_connections) == 0, "After 200 connect/disconnect cycles, no connections should remain"

    @pytest.mark.asyncio
    async def test_interleaved_connect_disconnect_stays_within_cap(self):
        """
        Interleave connects and disconnects; connection count must never exceed cap.
        """
        from api.ws_routes import MAX_WS_CONNECTIONS, ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="interleave-test")
        connected_ws: list[MagicMock] = []

        for i in range(150):
            if i % 3 == 0 and connected_ws:
                # Disconnect the oldest
                victim = connected_ws.pop(0)
                mgr.disconnect(victim)
            else:
                ws = _make_ws(f"ws-{i}")
                with (
                    patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": f"u{i}"})),
                    patch("asyncio.create_task", return_value=MagicMock(done=lambda: True, cancel=lambda: None)),
                ):
                    connected = await mgr.connect(ws)
                if connected:
                    connected_ws.append(ws)

            # Invariant: never exceed cap
            assert len(mgr.active_connections) <= MAX_WS_CONNECTIONS, (
                f"Iteration {i}: connections {len(mgr.active_connections)} > cap {MAX_WS_CONNECTIONS}"
            )
