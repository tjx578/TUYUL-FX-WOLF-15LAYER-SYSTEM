"""
Tests for WebSocket v3 upgrades:
  - ConnectionManager heartbeat + message buffer + replay
  - Event-driven price notification (_price_event)
  - Cached risk singletons (_get_risk_manager / _get_circuit_breaker)
  - Exponential backoff helper (frontend-side, tested conceptually)
"""

import time

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# ConnectionManager: buffer + replay
# ---------------------------------------------------------------------------

class TestConnectionManagerBuffer:
    """Message buffer stores recent messages and replays on reconnect."""

    def _make_manager(self):
        from api.ws_routes import ConnectionManager  # noqa: PLC0415
        return ConnectionManager(name="test", buffer_size=5)

    def test_buffer_stores_messages(self):
        mgr = self._make_manager()
        for i in range(3):
            mgr.buffer_message({"type": "tick", "ts": float(i), "i": i})
        assert len(mgr._message_buffer) == 3

    def test_buffer_ring_evicts_oldest(self):
        mgr = self._make_manager()
        for i in range(10):
            mgr.buffer_message({"type": "tick", "ts": float(i), "i": i})
        # Buffer size is 5 — only messages 5–9 should remain
        assert len(mgr._message_buffer) == 5
        assert mgr._message_buffer[0]["i"] == 5
        assert mgr._message_buffer[-1]["i"] == 9

    @pytest.mark.asyncio
    async def test_replay_all_when_no_since(self):
        mgr = self._make_manager()
        for i in range(3):
            mgr.buffer_message({"type": "tick", "ts": float(i + 1), "i": i})

        ws = AsyncMock()
        await mgr.replay_buffer(ws, since_ts=None)
        assert ws.send_json.call_count == 3

    @pytest.mark.asyncio
    async def test_replay_filters_by_since(self):
        mgr = self._make_manager()
        mgr.buffer_message({"type": "tick", "ts": 1.0, "i": 0})
        mgr.buffer_message({"type": "tick", "ts": 2.0, "i": 1})
        mgr.buffer_message({"type": "tick", "ts": 3.0, "i": 2})

        ws = AsyncMock()
        await mgr.replay_buffer(ws, since_ts=1.5)
        # Should only replay ts=2.0 and ts=3.0
        assert ws.send_json.call_count == 2


# ---------------------------------------------------------------------------
# Cached risk singletons
# ---------------------------------------------------------------------------

class TestCachedRiskSingletons:
    """Risk WS should use cached singletons, not re-instantiate."""

    def test_get_risk_manager_caches(self):
        import api.ws_routes as mod  # noqa: PLC0415
        mod._cached_risk_manager = None  # reset

        # Patch the import to return a mock
        mock_rm = MagicMock()
        mock_rm.get_risk_snapshot.return_value = {"balance": 10000}

        mock_class = MagicMock()
        mock_class.get_instance.return_value = mock_rm

        with patch.dict("sys.modules", {"risk.risk_manager": MagicMock(RiskManager=mock_class)}):
            mod._cached_risk_manager = None
            # First call creates
            result1 = mod._get_risk_manager()
            # Second call returns cached
            result2 = mod._get_risk_manager()
            assert result1 is result2

        # Cleanup
        mod._cached_risk_manager = None

    def test_get_circuit_breaker_caches(self):
        import api.ws_routes as mod  # noqa: PLC0415
        mod._cached_circuit_breaker = None

        mock_cb = MagicMock()
        mod._cached_circuit_breaker = mock_cb

        result = mod._get_circuit_breaker()
        assert result is mock_cb

        # Cleanup
        mod._cached_circuit_breaker = None


# ---------------------------------------------------------------------------
# Event-driven price notification
# ---------------------------------------------------------------------------

class TestPriceEvent:
    """_price_event should be set when notify_price_update is called."""

    @pytest.mark.asyncio
    async def test_notify_sets_event(self):
        from api.ws_routes import _price_event, notify_price_update  # noqa: PLC0415

        _price_event.clear()
        assert not _price_event.is_set()

        await notify_price_update()
        assert _price_event.is_set()

    @pytest.mark.asyncio
    async def test_event_clears_after_read(self):
        from api.ws_routes import _price_event, notify_price_update  # noqa: PLC0415

        await notify_price_update()
        assert _price_event.is_set()

        _price_event.clear()
        assert not _price_event.is_set()


# ---------------------------------------------------------------------------
# Heartbeat configuration
# ---------------------------------------------------------------------------

class TestHeartbeatConfig:
    """Verify heartbeat constants are reasonable."""

    def test_ping_interval_is_positive(self):
        from api.ws_routes import WS_PING_INTERVAL, WS_PONG_TIMEOUT  # noqa: PLC0415
        assert WS_PING_INTERVAL > 0
        assert WS_PONG_TIMEOUT > 0
        assert WS_PING_INTERVAL > WS_PONG_TIMEOUT  # ping interval > pong timeout


# ---------------------------------------------------------------------------
# Broadcast also buffers
# ---------------------------------------------------------------------------

class TestBroadcastBuffers:
    """broadcast() should add message to buffer."""

    @pytest.mark.asyncio
    async def test_broadcast_adds_to_buffer(self):
        from api.ws_routes import ConnectionManager  # noqa: PLC0415
        mgr = ConnectionManager(name="test-broadcast", buffer_size=10)

        msg = {"type": "tick", "data": {"EURUSD": {}}, "ts": time.time()}
        await mgr.broadcast(msg)

        assert len(mgr._message_buffer) == 1
        assert mgr._message_buffer[0] is msg
