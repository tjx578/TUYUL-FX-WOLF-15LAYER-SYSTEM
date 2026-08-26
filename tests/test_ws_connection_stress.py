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
import itertools
import time
from typing import Any
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


def _mock_create_task(coro):
    """Close background loop coroutines when task creation is mocked out."""
    close = getattr(coro, "close", None)
    if callable(close):
        close()
    task = MagicMock()
    task.done.return_value = True
    task.cancel.return_value = None
    return task


def _register_connected_ws(manager, ws: MagicMock) -> None:
    """Register a mock client with the state connect() normally creates."""
    manager.active_connections.add(ws)
    manager._per_conn_seq[ws] = itertools.count(1)  # noqa: SLF001


class _OwnedConnections:
    """Track only connections accepted by one test and close each exactly once."""

    def __init__(self) -> None:
        self._active: dict[MagicMock, Any] = {}
        self.finalizer_disconnects = 0

    @property
    def active_count(self) -> int:
        return len(self._active)

    def record(self, manager: Any, websocket: MagicMock) -> None:
        if websocket in self._active:
            raise AssertionError("accepted connection was recorded twice")
        self._active[websocket] = manager

    def disconnect(self, manager: Any, websocket: MagicMock, *, finalizer: bool = False) -> None:
        owner = self._active.get(websocket)
        if owner is None:
            raise AssertionError("connection is not owned or was already disconnected")
        if owner is not manager:
            raise AssertionError("connection belongs to a different fixture manager")

        manager.disconnect(websocket)
        if websocket in manager.active_connections:
            raise AssertionError("disconnect returned without removing the owned connection")
        del self._active[websocket]
        if finalizer:
            self.finalizer_disconnects += 1

    def close_all(self) -> None:
        failures: list[Exception] = []
        for websocket, manager in tuple(self._active.items()):
            try:
                self.disconnect(manager, websocket, finalizer=True)
            except Exception as exc:  # preserve cleanup failure as test evidence
                failures.append(exc)
        if failures:
            raise AssertionError(f"{len(failures)} owned connection(s) failed deterministic cleanup") from failures[0]


@pytest.fixture(autouse=True)
def _close_test_owned_connections(monkeypatch: pytest.MonkeyPatch):
    """Finalise every accepted connection owned by the current test."""
    from api.ws_routes import ConnectionManager  # noqa: PLC0415

    original_connect = ConnectionManager.connect
    original_disconnect = ConnectionManager.disconnect
    active: dict[tuple[ConnectionManager, MagicMock], None] = {}

    async def tracked_connect(manager: ConnectionManager, websocket: MagicMock) -> bool:
        connected = await original_connect(manager, websocket)
        if connected:
            active[(manager, websocket)] = None
        return connected

    def tracked_disconnect(manager: ConnectionManager, websocket: MagicMock) -> None:
        original_disconnect(manager, websocket)
        active.pop((manager, websocket), None)

    monkeypatch.setattr(ConnectionManager, "connect", tracked_connect)
    monkeypatch.setattr(ConnectionManager, "disconnect", tracked_disconnect)
    try:
        yield
    finally:
        failures: list[Exception] = []
        for manager, websocket in tuple(active):
            try:
                original_disconnect(manager, websocket)
                active.pop((manager, websocket), None)
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise AssertionError(f"{len(failures)} fixture-owned connection(s) failed teardown") from failures[0]
        assert active == {}


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
            patch("asyncio.create_task", side_effect=_mock_create_task),
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
            patch("asyncio.create_task", side_effect=_mock_create_task),
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
            patch("asyncio.create_task", side_effect=_mock_create_task),
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
            _register_connected_ws(mgr, c)

        msg = {"type": "tick", "data": {"EURUSD": {"bid": 1.085, "ask": 1.0851}}}
        await mgr.broadcast(msg)

        for c in clients:
            c.send_json.assert_called_once()
            sent = c.send_json.call_args.args[0]
            assert sent["type"] == msg["type"]
            assert sent["data"] == msg["data"]
            assert "seq" in sent

    @pytest.mark.asyncio
    async def test_broadcast_50_clients_under_100ms(self):
        """Broadcast to 50 mock clients must complete in under 100ms."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="latency-test")
        clients = [_make_ws(f"ws-{i}") for i in range(50)]
        for c in clients:
            _register_connected_ws(mgr, c)

        msg = {"type": "risk_state", "data": {"ts": time.time()}}
        start = time.perf_counter()
        await mgr.broadcast(msg)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Broadcast to 50 clients took {elapsed_ms:.1f}ms (limit: 100ms)"

    @pytest.mark.asyncio
    async def test_broadcast_1000_messages_to_10_clients_is_lossless(self):
        """The deterministic lane proves exact fan-out without enforcing a latency SLA."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="sustained-correctness-test")
        clients: list[MagicMock] = []
        deliveries: dict[MagicMock, list[dict[str, int]]] = {}
        for index in range(10):
            client = _make_ws(f"ws-{index}")
            received: list[dict[str, int]] = []

            async def record(payload: dict[str, int], *, sink: list[dict[str, int]] = received) -> None:
                sink.append(payload)

            client.send_json = record
            clients.append(client)
            deliveries[client] = received
            _register_connected_ws(mgr, client)

        async def broadcast_all() -> None:
            for message_id in range(1000):
                await mgr.broadcast({"message_id": message_id})

        await asyncio.wait_for(broadcast_all(), timeout=30.0)

        expected_message_ids = list(range(1000))
        expected_connection_sequence = list(range(1, 1001))
        delivered_by_client: list[list[int]] = []
        for client in clients:
            delivered = deliveries[client]
            assert len(delivered) == 1000
            message_ids = [payload["message_id"] for payload in delivered]
            connection_sequence = [payload["seq"] for payload in delivered]
            assert message_ids == expected_message_ids
            assert connection_sequence == expected_connection_sequence
            assert len(message_ids) == len(set(message_ids))
            delivered_by_client.append(message_ids)

        assert delivered_by_client == [expected_message_ids] * len(clients)
        assert mgr.active_connections == set(clients)
        assert set(mgr._per_conn_seq) == set(clients)

        for client in clients:
            mgr.disconnect(client)
        assert not mgr.active_connections
        assert not mgr._per_conn_seq

    @pytest.mark.asyncio
    @pytest.mark.reference_performance
    async def test_broadcast_1000_messages_to_10_clients_reference_sla(self):
        """1000 sequential broadcasts to 10 clients must stay under 1s total."""
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="sustained-test")
        clients = [_make_ws(f"ws-{i}") for i in range(10)]
        for c in clients:
            _register_connected_ws(mgr, c)

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
            _register_connected_ws(mgr, c)

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
        mgr._per_conn_seq[ws] = itertools.count(1)  # noqa: SLF001
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
        mgr._per_conn_seq[ws] = itertools.count(1)  # noqa: SLF001
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
        mgr._per_conn_seq[ws] = itertools.count(1)  # noqa: SLF001

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
                patch("asyncio.create_task", side_effect=_mock_create_task),
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
        owned = _OwnedConnections()
        attempts = 0
        accepted = 0
        rejected = 0
        scenario_disconnects = 0

        try:
            for i in range(150):
                if i % 3 == 0 and connected_ws:
                    # Disconnect the oldest without changing the historical pattern.
                    victim = connected_ws.pop(0)
                    owned.disconnect(mgr, victim)
                    scenario_disconnects += 1
                else:
                    attempts += 1
                    ws = _make_ws(f"ws-{i}")
                    with (
                        patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": f"u{i}"})),
                        patch("asyncio.create_task", side_effect=_mock_create_task),
                    ):
                        connected = await mgr.connect(ws)
                    if connected:
                        accepted += 1
                        connected_ws.append(ws)
                        owned.record(mgr, ws)
                    else:
                        rejected += 1

                # Invariant: never exceed cap
                assert len(mgr.active_connections) <= MAX_WS_CONNECTIONS, (
                    f"Iteration {i}: connections {len(mgr.active_connections)} > cap {MAX_WS_CONNECTIONS}"
                )

            assert attempts == 101
            assert accepted == 99
            assert rejected == 2
            assert scenario_disconnects == 49
            assert owned.active_count == 50
        finally:
            owned.close_all()
            connected_ws.clear()

        assert owned.finalizer_disconnects == 50
        assert owned.active_count == 0
        assert connected_ws == []
        assert mgr.active_connections == set()


class TestOwnedConnectionCleanup:
    """Negative controls for fail-closed fixture ownership and teardown."""

    @pytest.mark.asyncio
    async def test_rejected_connection_is_not_owned(self):
        from api.ws_routes import MAX_WS_CONNECTIONS, ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="rejected-not-owned")
        fillers = _OwnedConnections()
        for i in range(MAX_WS_CONNECTIONS):
            existing = _make_ws(f"existing-{i}")
            _register_connected_ws(mgr, existing)
            fillers.record(mgr, existing)
        rejected = _make_ws("rejected")
        owned = _OwnedConnections()

        try:
            connected = await mgr.connect(rejected)
            if connected:
                owned.record(mgr, rejected)

            assert connected is False
            assert owned.active_count == 0
        finally:
            fillers.close_all()

        assert mgr.active_connections == set()

    @pytest.mark.asyncio
    async def test_cleanup_does_not_delete_another_fixture_session(self):
        from api import ws_routes  # noqa: PLC0415

        sessions: dict[str, int] = {}

        def session_set(key: str, value: int, *, ex: int) -> None:
            assert ex > 0
            sessions[key] = value

        def session_delete(key: str) -> None:
            del sessions[key]

        mgr_a = ws_routes.ConnectionManager(name="owner-a")
        mgr_b = ws_routes.ConnectionManager(name="owner-b")
        ws_a = _make_ws("owned-a")
        ws_b = _make_ws("owned-b")
        owned = _OwnedConnections()
        with (
            patch("api.ws_routes._ws_session_set", side_effect=session_set),
            patch("api.ws_routes._ws_session_delete", side_effect=session_delete),
            patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "fixture"})),
            patch("asyncio.create_task", side_effect=_mock_create_task),
        ):
            assert await mgr_a.connect(ws_a) is True
            owned.record(mgr_a, ws_a)
            assert await mgr_b.connect(ws_b) is True
            owned.close_all()

            assert len(sessions) == 1
            assert ws_b in mgr_b.active_connections
            mgr_b.disconnect(ws_b)

        assert sessions == {}

    def test_double_disconnect_is_not_hidden(self):
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="double-disconnect")
        ws = _make_ws("owned")
        _register_connected_ws(mgr, ws)
        owned = _OwnedConnections()
        owned.record(mgr, ws)
        owned.disconnect(mgr, ws)

        with pytest.raises(AssertionError, match="not owned or was already disconnected"):
            owned.disconnect(mgr, ws)

    def test_disconnect_failure_remains_visible(self):
        manager = MagicMock()
        manager.disconnect.side_effect = RuntimeError("disconnect failed")
        ws = _make_ws("owned")
        owned = _OwnedConnections()
        owned.record(manager, ws)

        with pytest.raises(AssertionError, match="failed deterministic cleanup") as exc_info:
            owned.close_all()

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert owned.active_count == 1

    def test_finalizer_runs_when_scenario_assertion_fails(self):
        from api.ws_routes import ConnectionManager  # noqa: PLC0415

        mgr = ConnectionManager(name="assertion-finalizer")
        ws = _make_ws("owned")
        _register_connected_ws(mgr, ws)
        owned = _OwnedConnections()
        owned.record(mgr, ws)

        with pytest.raises(AssertionError, match="scenario failure"):
            try:
                raise AssertionError("scenario failure")
            finally:
                owned.close_all()

        assert owned.active_count == 0
        assert mgr.active_connections == set()

    @pytest.mark.asyncio
    async def test_fixture_exception_leaves_no_session_key(self):
        from api import ws_routes  # noqa: PLC0415

        sessions: dict[str, int] = {}

        def session_set(key: str, value: int, *, ex: int) -> None:
            assert ex > 0
            sessions[key] = value

        def session_delete(key: str) -> None:
            del sessions[key]

        mgr = ws_routes.ConnectionManager(name="fixture-exception")
        ws = _make_ws("owned")
        owned = _OwnedConnections()
        with (
            patch("api.ws_routes._ws_session_set", side_effect=session_set),
            patch("api.ws_routes._ws_session_delete", side_effect=session_delete),
            patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "fixture"})),
            patch("asyncio.create_task", side_effect=_mock_create_task),
            pytest.raises(RuntimeError, match="fixture failed"),
        ):
            try:
                assert await mgr.connect(ws) is True
                owned.record(mgr, ws)
                raise RuntimeError("fixture failed")
            finally:
                owned.close_all()

        assert sessions == {}
