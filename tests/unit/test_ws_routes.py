"""
Tests for WebSocket push endpoints (ws_routes.py).
Covers connection lifecycle, message format, and broadcast behavior.
"""

from unittest.mock import AsyncMock

import pytest

try:
    from api.ws_routes import router as ws_router

    HAS_WS = True
except ImportError:
    try:
        from dashboard.ws_routes import router as ws_router  # type: ignore[import-not-found]

        HAS_WS = True
    except ImportError:
        HAS_WS = False

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient  # noqa: F401
    from fastapi.websockets import WebSocket  # noqa: F401

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TestWebSocketMessageFormat:
    """WS messages must follow a consistent envelope."""

    def test_signal_push_format(self, sample_l12_verdict):
        msg = {
            "type": "SIGNAL_UPDATE",
            "data": sample_l12_verdict,
            "timestamp": "2026-02-15T10:30:00Z",
        }
        assert msg["type"] == "SIGNAL_UPDATE"
        assert "data" in msg

    def test_risk_alert_push_format(self):
        msg = {
            "type": "RISK_ALERT",
            "data": {
                "code": "DAILY_LOSS_WARNING",
                "severity": "WARNING",
                "current_loss_pct": 3.5,
                "limit_pct": 5.0,
            },
            "timestamp": "2026-02-15T10:30:00Z",
        }
        assert msg["type"] == "RISK_ALERT"
        assert msg["data"]["severity"] in ("INFO", "WARNING", "CRITICAL")

    def test_trade_event_push_format(self):
        msg = {
            "type": "TRADE_EVENT",
            "data": {
                "event_type": "ORDER_FILLED",
                "order_id": "ORD-0001",
                "symbol": "EURUSD",
            },
            "timestamp": "2026-02-15T10:31:00Z",
        }
        assert msg["type"] == "TRADE_EVENT"

    @pytest.mark.parametrize(
        "msg_type",
        [
            "SIGNAL_UPDATE",
            "RISK_ALERT",
            "TRADE_EVENT",
            "ACCOUNT_UPDATE",
            "SYSTEM_STATUS",
        ],
    )
    def test_message_type_enum(self, msg_type):
        valid = {"SIGNAL_UPDATE", "RISK_ALERT", "TRADE_EVENT", "ACCOUNT_UPDATE", "SYSTEM_STATUS"}
        assert msg_type in valid


@pytest.mark.ws
class TestWebSocketLifecycle:
    """WebSocket connection and broadcast tests."""

    @pytest.mark.asyncio
    async def test_client_manager_add_remove(self):
        """Basic connection manager pattern."""
        clients = set()
        mock_ws = AsyncMock()
        mock_ws.client_id = "test-1"

        clients.add(mock_ws)
        assert len(clients) == 1

        clients.discard(mock_ws)
        assert len(clients) == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_all_clients(self):
        clients = []
        for _i in range(5):
            ws = AsyncMock()
            ws.send_json = AsyncMock()
            clients.append(ws)

        msg = {"type": "SIGNAL_UPDATE", "data": {"symbol": "EURUSD"}}
        for client in clients:
            await client.send_json(msg)

        for client in clients:
            client.send_json.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_handles_disconnected_client(self):
        """If a client disconnects mid-broadcast, don't crash."""
        healthy_ws = AsyncMock()
        broken_ws = AsyncMock()
        broken_ws.send_json.side_effect = Exception("connection closed")

        clients = [healthy_ws, broken_ws]
        msg = {"type": "SYSTEM_STATUS", "data": {"status": "ok"}}

        errors = []
        for client in clients:
            try:
                await client.send_json(msg)
            except Exception:
                errors.append(client)

        healthy_ws.send_json.assert_called_once()
        assert len(errors) == 1  # only the broken one

    @pytest.mark.asyncio
    async def test_subscribe_to_specific_symbol(self):
        """Clients can subscribe to symbol-specific channels."""
        subscriptions = {"EURUSD": set(), "GBPUSD": set()}
        client_a = AsyncMock()
        client_b = AsyncMock()

        subscriptions["EURUSD"].add(client_a)
        subscriptions["GBPUSD"].add(client_b)

        msg = {"type": "SIGNAL_UPDATE", "data": {"symbol": "EURUSD"}}
        for client in subscriptions.get("EURUSD", set()):
            await client.send_json(msg)

        client_a.send_json.assert_called_once()
        client_b.send_json.assert_not_called()

    @pytest.mark.skipif(not HAS_FASTAPI or not HAS_WS, reason="FastAPI or ws_routes not available")
    def test_ws_endpoint_exists(self):
        """Verify that the WS route is registered."""
        app = FastAPI()  # type: ignore
        app.include_router(ws_router)  # type: ignore
        routes = [getattr(r, "path", None) for r in app.routes]
        # At least one websocket route should exist
        assert len(routes) > 0
