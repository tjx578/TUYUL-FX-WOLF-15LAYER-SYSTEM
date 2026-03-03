from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.accounts_router import router as accounts_router
from api.config_profile_router import router as config_profile_router
from api.signals_router import router as signals_router
from api.ws_routes import router as ws_router
from config.profile_engine import ConfigProfileEngine
from risk.kill_switch import GlobalKillSwitch
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION
from schemas.validator import validate_signal_contract


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(signals_router)
    app.include_router(accounts_router)
    app.include_router(config_profile_router)
    app.include_router(ws_router)
    return app


def test_signal_contract_frozen_version_rejects_mismatch() -> None:
    valid_payload = {
        "contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,
        "signal_id": "SIG-TEST-1",
        "symbol": "EURUSD",
        "verdict": "HOLD",
        "confidence": 0.5,
        "timestamp": 1_762_000_000.0,
    }
    ok, errors = validate_signal_contract(valid_payload)
    assert ok is True
    assert errors == []

    invalid_payload = dict(valid_payload)
    invalid_payload["contract_version"] = "2025-01-01"
    ok2, errors2 = validate_signal_contract(invalid_payload)
    assert ok2 is False
    assert any("Frozen SignalContract mismatch" in e for e in errors2)


def test_read_only_apis_expose_get_only() -> None:
    app = _build_app()
    client = TestClient(app)

    assert client.get("/api/v1/signals").status_code == 200
    assert client.get("/api/v1/accounts").status_code == 200
    assert client.post("/api/v1/signals", json={}).status_code == 405
    assert client.post("/api/v1/accounts", json={}).status_code == 405


def test_config_profile_engine_activation() -> None:
    engine = ConfigProfileEngine()
    result = engine.activate("conservative")
    assert result["active_profile"] == "conservative"
    risk_cfg = result["effective_config"]["risk"]["position_sizing"]
    assert risk_cfg["default_risk_percent"] == 0.005


def test_global_kill_switch_toggle() -> None:
    ks = GlobalKillSwitch()
    enabled = ks.enable("TEST_HALT")
    assert enabled["enabled"] is True
    assert ks.is_enabled() is True

    disabled = ks.disable("TEST_RESUME")
    assert disabled["enabled"] is False
    assert ks.is_enabled() is False


def test_ws_live_feed_endpoint_snapshot() -> None:
    app = _build_app()
    client = TestClient(app)

    with patch("api.ws_routes.ws_auth_guard", new=AsyncMock(return_value={"sub": "test-user"})):
        with client.websocket_connect("/ws/live?token=dummy") as ws:
            message = ws.receive_json()
            assert message["type"] == "snapshot"
            assert "signals" in message["data"]
            assert "accounts" in message["data"]
