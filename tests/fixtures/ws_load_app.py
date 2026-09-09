"""TEST_ONLY socket fixture: production routes/auth, deterministic reader inputs.

No application workers, producer, broker or deployment is started. Built API
lifespan acceptance is exercised separately by built_api_acceptance.py.
"""

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import uvicorn


def main():
    from api import ws_routes as routes
    from api.app_factory import create_app

    app = create_app()
    routes._price_feed = SimpleNamespace(get_latest_prices_async=AsyncMock(return_value={}))
    routes._trade_ledger = SimpleNamespace(get_active_trades_async=AsyncMock(return_value=[]))
    routes.AccountManager.list_accounts_async = AsyncMock(return_value=[])
    routes.AccountManager.get_account_async = AsyncMock(return_value=None)
    routes._candle_agg = SimpleNamespace(
        get_combined_snapshot=lambda *_: {},
        fetch_feed_meta_async=AsyncMock(return_value={"ingest_status": "NO_PRODUCER"}),
        fetch_forming_bars_async=AsyncMock(return_value={}),
    )
    routes._get_circuit_breaker = lambda: SimpleNamespace(state="OPEN")
    routes._get_risk_manager = lambda: None
    # Only the session store is a fixture. Authentication and connection/task
    # lifecycle use the real production manager without monkeypatching guards.
    routes._ws_session_set = lambda *_, **__: None
    routes._ws_session_delete = lambda *_: None
    managers = {
        channel: getattr(routes, f"{name}_manager")
        for channel, name in (
            ("prices", "price"),
            ("trades", "trade"),
            ("candles", "candle"),
            ("risk", "risk"),
            ("equity", "equity"),
        )
    }

    @app.get("/__test_only/ws-state")
    async def state():
        return {
            channel: {
                "connections": len(manager.active_connections),
                "ping_tasks": len(manager._ping_tasks),
                "receive_tasks": len(manager._recv_tasks),
                "sessions": len(manager._session_keys),
                "send_locks": len(manager._send_locks),
                "sequences": len(manager._per_conn_seq),
            }
            for channel, manager in managers.items()
        }

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        Path(sys.argv[1]).write_text(json.dumps({"host": "127.0.0.1", "port": port}))
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="warning"))
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
