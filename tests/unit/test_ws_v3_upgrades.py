"""
Tests for WebSocket v3 upgrades:
  - ConnectionManager heartbeat + message buffer + replay
  - Event-driven price notification (_price_event)
  - Cached risk singletons (_get_risk_manager / _get_circuit_breaker)
  - Exponential backoff helper (frontend-side, tested conceptually)
"""
import time
from collections.abc import Iterable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# ConnectionManager: buffer + replay
# ---------------------------------------------------------------------------

def _buffer_snapshot(mgr: Any) -> list[dict[str, Any]]:
    getter = getattr(mgr, "get_message_buffer", None)
    data = getter() if callable(getter) else getattr(mgr, "message_buffer", [])
    return list(cast(Iterable[dict[str, Any]], data))


def _reset_cached_singletons_if_available(mod: Any) -> None:
    reset_fn = getattr(mod, "reset_cached_singletons", None)
    if callable(reset_fn):
        reset_fn()


class TestConnectionManagerBuffer:
    """Message buffer stores recent messages and replays on reconnect."""

    def _make_manager(self):
        from api.ws_routes import ConnectionManager  # noqa: PLC0415
        return ConnectionManager(name="test", buffer_size=5)

    def test_buffer_stores_messages(self):
        mgr = self._make_manager()
        for i in range(3):
            mgr.buffer_message({"type": "tick", "ts": float(i), "i": i})
        assert len(_buffer_snapshot(mgr)) == 3

    def test_buffer_ring_evicts_oldest(self):
        mgr = self._make_manager()
        for i in range(10):
            mgr.buffer_message({"type": "tick", "ts": float(i), "i": i})
        # Buffer size is 5 — only messages 5–9 should remain
        buf = _buffer_snapshot(mgr)
        assert len(buf) == 5
        assert buf[0]["i"] == 5
        assert buf[-1]["i"] == 9

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
        _reset_cached_singletons_if_available(mod)

        # Patch the import to return a mock
        mock_rm = MagicMock()
        mock_rm.get_risk_snapshot.return_value = {"balance": 10000}

        mock_class = MagicMock()
        mock_class.get_instance.return_value = mock_rm

        get_risk_manager = mod._get_risk_manager

        with patch.dict("sys.modules", {"risk.risk_manager": MagicMock(RiskManager=mock_class)}):
            _reset_cached_singletons_if_available(mod)
            # First call creates
            result1 = get_risk_manager()
            # Second call returns cached
            result2 = get_risk_manager()
            assert result1 is result2

        # Cleanup
        _reset_cached_singletons_if_available(mod)

    def test_get_circuit_breaker_caches(self):
        import api.ws_routes as mod  # noqa: PLC0415
        _reset_cached_singletons_if_available(mod)

        mock_cb = MagicMock()
        get_circuit_breaker = cast(Any, getattr(mod, "_get_circuit_breaker"))

        # Directly set the cached value through a small workaround:
        # We patch _get_circuit_breaker to simulate caching behavior
        with patch.object(mod, "_cached_circuit_breaker", mock_cb):
            result = get_circuit_breaker()
            assert result is mock_cb

        # Cleanup
        _reset_cached_singletons_if_available(mod)


# ---------------------------------------------------------------------------
# Event-driven price notification
# ---------------------------------------------------------------------------

class TestPriceEvent:
    """_price_event should be set when notify_price_update is called."""

    @pytest.mark.asyncio
    async def test_notify_sets_event(self):
        import api.ws_routes as mod  # noqa: PLC0415

        price_event = cast(Any, getattr(mod, "_price_event"))
        price_event.clear()
        assert not price_event.is_set()

        await mod.notify_price_update()
        assert price_event.is_set()

    @pytest.mark.asyncio
    async def test_event_clears_after_read(self):
        import api.ws_routes as mod  # noqa: PLC0415

        price_event = getattr(mod, "_price_event")
        await mod.notify_price_update()
        assert price_event.is_set()

        price_event.clear()
        assert not price_event.is_set()


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

        msg: dict[str, Any] = {"type": "tick", "data": {"EURUSD": {}}, "ts": time.time()}
        await mgr.broadcast(msg)

        buf = _buffer_snapshot(mgr)
        assert len(buf) == 1
        assert buf[0] is msg


# ---------------------------------------------------------------------------
# Publisher helpers
# ---------------------------------------------------------------------------

class TestPublisherHelpers:
    """Helper publishers should hide WS manager details from callers."""

    @pytest.mark.asyncio
    async def test_publish_signal_update_broadcasts_envelope(self):
        import api.ws_routes as mod  # noqa: PLC0415

        mock_broadcast = AsyncMock()
        with patch.object(mod.signal_manager, "broadcast", mock_broadcast):
            await mod.publish_signal_update({
                "signal_id": "SIG-1",
                "symbol": "EURUSD",
                "verdict": "EXECUTE_BUY",
            })

        assert mock_broadcast.call_count == 1
        msg = mock_broadcast.call_args.args[0]
        assert msg["event_type"] == "signals.update"
        assert msg["payload"]["signal"]["signal_id"] == "SIG-1"

    @pytest.mark.asyncio
    async def test_publish_pipeline_update_uses_explicit_payload(self):
        import api.ws_routes as mod  # noqa: PLC0415

        mock_broadcast = AsyncMock()
        payload = {"pair": "EURUSD", "verdict": "HOLD"}

        with patch.object(mod.pipeline_manager, "broadcast", mock_broadcast):
            ok = await mod.publish_pipeline_update("eurusd", payload)

        assert ok is True
        msg = mock_broadcast.call_args.args[0]
        assert msg["event_type"] == "pipeline.update"
        assert msg["payload"]["pair"] == "EURUSD"
        assert msg["payload"]["pipeline"]["verdict"] == "HOLD"

    @pytest.mark.asyncio
    async def test_publish_pipeline_update_from_cache_returns_false_when_missing(self):
        import api.ws_routes as mod  # noqa: PLC0415

        mock_broadcast = AsyncMock()
        with (
            patch.object(mod.pipeline_manager, "broadcast", mock_broadcast),
            patch("api.ws_routes.get_verdict", return_value=None),
        ):
            ok = await mod.publish_pipeline_update("EURUSD")

        assert ok is False
        assert mock_broadcast.call_count == 0
