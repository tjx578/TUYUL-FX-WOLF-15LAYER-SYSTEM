from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config_profile_router import router as config_profile_router
from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext, enforce_write_policy
from config.profile_engine import ConfigProfileEngine


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(config_profile_router)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}
    app.dependency_overrides[enforce_write_policy] = lambda: GovernanceContext(
        role="admin",
        actor="test-admin",
        auth_method="jwt",
        scopes=frozenset({"*"}),
        reason="TEST_WRITE",
    )
    return app


def _reset_engine_state() -> None:
    engine = ConfigProfileEngine()

    if engine.is_locked():
        engine.set_lock(False, actor="test-admin", reason="RESET_UNLOCK")

    if engine.get_active_profile() != "default":
        engine.activate("default", actor="test-admin", reason="RESET_ACTIVE")

    overrides = engine.list_overrides()
    for scope, entries in overrides.items():
        for key in list(entries.keys()):
            engine.delete_override(scope, key, actor="test-admin", reason="RESET_OVERRIDE")

    for record in engine.list_profile_records():
        if record["source"] != "runtime":
            continue
        engine.delete_profile(record["profile_name"], actor="test-admin", reason="RESET_PROFILE")



def test_profile_crud_on_new_endpoint_and_legacy_compatibility() -> None:
    _reset_engine_state()
    app = _build_app()
    client = TestClient(app)

    list_resp = client.get("/api/v1/config/profile")
    assert list_resp.status_code == 200
    assert "default" in list_resp.json()["profile_names"]

    create_resp = client.post(
        "/api/v1/config/profile",
        json={
            "profile_name": "swing_test",
            "profile": {"risk": {"position_sizing": {"default_risk_percent": 0.007}}},
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["profile_name"] == "swing_test"

    detail_new = client.get("/api/v1/config/profile/swing_test")
    assert detail_new.status_code == 200
    assert detail_new.json()["profile"]["risk"]["position_sizing"]["default_risk_percent"] == 0.007

    detail_legacy = client.get("/api/v1/config/profiles/swing_test")
    assert detail_legacy.status_code == 200
    assert detail_legacy.json()["profile_name"] == "swing_test"

    update_resp = client.put(
        "/api/v1/config/profile/swing_test",
        json={
            "profile": {
                "risk": {"position_sizing": {"default_risk_percent": 0.009}},
                "execution": {"max_concurrent_positions": 2},
            }
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["profile"]["risk"]["position_sizing"]["default_risk_percent"] == 0.009

    patch_resp = client.patch(
        "/api/v1/config/profile/swing_test",
        json={"profile": {"execution": {"allow_hedging": True}}},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["profile"]["execution"]["allow_hedging"] is True
    assert patch_resp.json()["profile"]["execution"]["max_concurrent_positions"] == 2

    activate_resp = client.post("/api/v1/config/profile/active", json={"profile_name": "swing_test"})
    assert activate_resp.status_code == 200
    assert activate_resp.json()["active_profile"] == "swing_test"

    delete_active_resp = client.delete("/api/v1/config/profile/swing_test")
    assert delete_active_resp.status_code == 409

    deactivate_resp = client.post("/api/v1/config/profile/active", json={"profile_name": "default"})
    assert deactivate_resp.status_code == 200

    delete_resp = client.delete("/api/v1/config/profile/swing_test")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    missing_resp = client.get("/api/v1/config/profile/swing_test")
    assert missing_resp.status_code == 404



def test_scoped_override_precedence_global_account_prop_firm_pair() -> None:
    _reset_engine_state()
    app = _build_app()
    client = TestClient(app)

    global_put = client.put(
        "/api/v1/config/profile/overrides/global/any",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.01}}}},
    )
    assert global_put.status_code == 200
    assert global_put.json()["key"] == "DEFAULT"

    account_put = client.put(
        "/api/v1/config/profile/overrides/account/acc_001",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.02}}}},
    )
    assert account_put.status_code == 200

    prop_put = client.put(
        "/api/v1/config/profile/overrides/prop_firm/ftmo",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.03}}}},
    )
    assert prop_put.status_code == 200

    pair_put = client.put(
        "/api/v1/config/profile/overrides/pair/eurusd",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.04}}}},
    )
    assert pair_put.status_code == 200

    effective_global = client.get("/api/v1/config/profile/effective")
    assert effective_global.status_code == 200
    assert effective_global.json()["effective_config"]["risk"]["position_sizing"]["default_risk_percent"] == 0.01

    effective_account = client.get("/api/v1/config/profile/effective", params={"account_id": "acc_001"})
    assert effective_account.status_code == 200
    assert effective_account.json()["effective_config"]["risk"]["position_sizing"]["default_risk_percent"] == 0.02

    effective_prop = client.get(
        "/api/v1/config/profile/effective",
        params={"account_id": "acc_001", "prop_firm": "ftmo"},
    )
    assert effective_prop.status_code == 200
    assert effective_prop.json()["effective_config"]["risk"]["position_sizing"]["default_risk_percent"] == 0.03

    effective_pair = client.get(
        "/api/v1/config/profile/effective",
        params={"account_id": "acc_001", "prop_firm": "ftmo", "pair": "eurusd"},
    )
    assert effective_pair.status_code == 200
    assert effective_pair.json()["effective_config"]["risk"]["position_sizing"]["default_risk_percent"] == 0.04

    read_override = client.get("/api/v1/config/profile/overrides/global/default")
    assert read_override.status_code == 200
    assert read_override.json()["exists"] is True
    assert read_override.json()["key"] == "DEFAULT"


def test_lock_blocks_override_writes_on_singular_path() -> None:
    _reset_engine_state()
    app = _build_app()
    client = TestClient(app)

    seed_resp = client.put(
        "/api/v1/config/profile/overrides/account/acc_lock_1",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.011}}}},
    )
    assert seed_resp.status_code == 200

    lock_resp = client.post("/api/v1/config/profile/lock", json={"locked": True})
    assert lock_resp.status_code == 200
    assert lock_resp.json()["locked"] is True

    blocked_put = client.put(
        "/api/v1/config/profile/overrides/account/acc_lock_1",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.05}}}},
    )
    assert blocked_put.status_code == 409

    blocked_delete = client.delete("/api/v1/config/profile/overrides/account/acc_lock_1")
    assert blocked_delete.status_code == 409

    read_locked = client.get("/api/v1/config/profile/overrides/account/acc_lock_1")
    assert read_locked.status_code == 200
    assert read_locked.json()["override"]["risk"]["position_sizing"]["default_risk_percent"] == 0.011

    unlock_resp = client.post("/api/v1/config/profile/lock", json={"locked": False})
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["locked"] is False

    put_after_unlock = client.put(
        "/api/v1/config/profile/overrides/account/acc_lock_1",
        json={"override": {"risk": {"position_sizing": {"default_risk_percent": 0.013}}}},
    )
    assert put_after_unlock.status_code == 200
    assert put_after_unlock.json()["override"]["risk"]["position_sizing"]["default_risk_percent"] == 0.013
