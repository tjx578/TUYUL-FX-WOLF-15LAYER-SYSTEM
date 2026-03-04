from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware import governance
from risk.risk_router import router as risk_router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(risk_router)
    return app


def _headers(pin: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer phase2-token",
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "PHASE2_TEST",
    }
    if pin is not None:
        headers["X-Action-Pin"] = pin
    return headers


def _base_context() -> dict:
    return {
        "prop_firm_code": "ftmo",
        "balance": 100000,
        "equity": 100000,
        "base_risk_percent": 0.7,
        "max_daily_loss_percent": 5.0,
        "max_total_loss_percent": 10.0,
        "daily_loss_used_percent": 1.0,
        "total_loss_used_percent": 1.0,
        "max_concurrent_trades": 2,
        "open_trades_count": 0,
        "correlation_bucket": "GREEN",
        "compliance_mode": True,
        "news_lock": False,
        "ea_instances": [
            {
                "ea_instance_id": "EA-H1",
                "strategy_profile": "H1",
                "risk_multiplier": 1.0,
                "enabled": True,
            }
        ],
    }


def test_context_rejects_compliance_off_without_pin(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    monkeypatch.setattr(
        governance,
        "decode_token",
        lambda _t: {"sub": "admin-1", "role": "admin", "iss": "issuer-A"},
    )
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "2468")

    payload = _base_context()
    payload["compliance_mode"] = False

    response = client.post(
        "/api/v1/risk/accounts/ACC-P2/context",
        headers=_headers(),
        json=payload,
    )
    assert response.status_code == 403
    assert "x-action-pin" in response.text.lower()


def test_context_rejects_prop_sovereignty_violation(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    monkeypatch.setattr(
        governance,
        "decode_token",
        lambda _t: {"sub": "admin-2", "role": "admin", "iss": "issuer-A"},
    )
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)

    payload = _base_context()
    payload["max_daily_loss_percent"] = 6.0  # FTMO template is 5.0

    response = client.post(
        "/api/v1/risk/accounts/ACC-P2/context",
        headers=_headers(),
        json=payload,
    )
    assert response.status_code == 422
    assert "prop_sovereignty" in response.text.lower()


def test_lockdown_mode_blocks_take(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    monkeypatch.setattr(
        governance,
        "decode_token",
        lambda _t: {"sub": "admin-3", "role": "admin", "iss": "issuer-A"},
    )
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)

    payload = _base_context()
    payload["abnormal_slippage"] = True

    save = client.post(
        "/api/v1/risk/accounts/ACC-P2-LOCK/context",
        headers=_headers(),
        json=payload,
    )
    assert save.status_code == 200
    assert save.json()["system_state"] == "LOCKDOWN"

    take = client.post(
        "/api/v1/risk/accounts/ACC-P2-LOCK/take",
        headers=_headers(),
        json={
            "signal_id": "SIG-P2",
            "ea_instance_id": "EA-H1",
            "requested_risk_percent": 0.5,
            "stop_loss_pips": 200,
            "pip_value_per_lot": 10,
            "operator": "desk",
            "reason": "TAKE",
        },
    )

    assert take.status_code == 200
    body = take.json()
    assert body["trade_allowed"] is False
    assert body["reason"] == "LOCKDOWN_ACTIVE"
