from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from api.owner_dashboard_release import DISABLED_FLAGS, main, validate_release_environment


def configured() -> dict[str, str]:
    salt = base64.urlsafe_b64encode(b"test-only-salt-16").decode()
    digest = base64.urlsafe_b64encode(b"x" * 32).decode()
    return {
        **dict.fromkeys(DISABLED_FLAGS, "false"),
        "DASHBOARD_OWNER_USERNAME": "synthetic-owner",
        "DASHBOARD_OWNER_PASSWORD_HASH": f"pbkdf2_sha256$600000${salt}${digest}",
        "DASHBOARD_JWT_SECRET": "synthetic-signing-secret-for-local-test-only",
    }


@pytest.mark.parametrize("flag", DISABLED_FLAGS)
@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "typo", ""])
def test_every_authority_flag_rejected(flag: str, value: str) -> None:
    env = configured()
    env[flag] = value
    with pytest.raises(ValueError, match=flag):
        validate_release_environment(env)


@pytest.mark.parametrize("key", ["DASHBOARD_OWNER_USERNAME", "DASHBOARD_OWNER_PASSWORD_HASH", "DASHBOARD_JWT_SECRET"])
def test_missing_identity_fails_closed(key: str) -> None:
    env = configured()
    del env[key]
    with pytest.raises(ValueError, match=key):
        validate_release_environment(env)


@pytest.mark.parametrize("value", ["bad", "pbkdf2_sha256$1$c2FsdA==$ZGlnaWVzdA==", "x" * 300])
def test_invalid_hash_is_never_echoed(value: str) -> None:
    env = configured()
    env["DASHBOARD_OWNER_PASSWORD_HASH"] = value
    with pytest.raises(ValueError) as exc:
        validate_release_environment(env)
    assert value not in str(exc.value)


def test_entrypoint_validates_before_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in configured().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    execute = Mock()
    monkeypatch.setattr(os, "execvp", execute)
    assert main() == 78
    execute.assert_not_called()
    monkeypatch.setenv("EXECUTION_ENABLED", "false")
    monkeypatch.setenv("WOLF15_API_READ_ONLY_STARTUP", "false")
    monkeypatch.setenv("WOLF15_SERVICE_ROLE", "test")
    assert main() == 0
    execute.assert_called_once_with("bash", ["bash", "deploy/railway/start_api.sh"])
    assert os.environ["WOLF15_API_READ_ONLY_STARTUP"] == "true"
    assert os.environ["WOLF15_SERVICE_ROLE"] == "api"


@pytest.mark.asyncio
async def test_real_lifespan_skips_background_writers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from fastapi import FastAPI

    from api import app_factory, ws_routes
    from infrastructure import cross_instance_relay, peer_health, redis_client
    from storage import trade_outbox_worker

    for key, value in configured().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WOLF15_API_READ_ONLY_STARTUP", "true")
    monkeypatch.setenv("WOLF15_SERVICE_ROLE", "api")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    redis = Mock(ping=AsyncMock(return_value=True))
    monkeypatch.setattr(redis_client, "get_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(redis_client, "close_pool", AsyncMock())
    initialize = AsyncMock()
    monkeypatch.setattr(app_factory.pg_client, "initialize", initialize)
    monkeypatch.setattr(app_factory.pg_client, "close", AsyncMock())
    constructors = [Mock(), Mock(), Mock()]
    monkeypatch.setattr(trade_outbox_worker, "TradeOutboxWorker", constructors[0])
    monkeypatch.setattr(cross_instance_relay, "CrossInstanceRelay", constructors[1])
    monkeypatch.setattr(peer_health, "PeerHealthChecker", constructors[2])
    candle_start = AsyncMock()
    monkeypatch.setattr(ws_routes._candle_agg, "start", candle_start)
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)
    app = FastAPI()
    async with app_factory.lifespan(app):
        assert app.state.trade_outbox_worker is None
        assert app.state.trade_outbox_task is None
    initialize.assert_not_awaited()
    candle_start.assert_not_awaited()
    thread.assert_not_called()
    for constructor in constructors:
        constructor.assert_not_called()
    output = capsys.readouterr().out
    line = next(line for line in output.splitlines() if line.startswith("WOLF15_OWNER_STARTUP_ATTESTATION "))
    receipt = json.loads(line.split(" ", 1)[1])
    assert all(receipt["disabled_flags"].values())
    assert not any(receipt["background_started"].values())
    assert len(receipt["files"]) == 4
    for key in ("DASHBOARD_OWNER_USERNAME", "DASHBOARD_OWNER_PASSWORD_HASH", "DASHBOARD_JWT_SECRET"):
        assert configured()[key] not in output


@pytest.mark.parametrize("background", ["outbox", "relay", "peer_health", "candle_aggregator", "orchestrator"])
def test_attestation_rejects_running_background_worker(monkeypatch: pytest.MonkeyPatch, background: str) -> None:
    from api.owner_dashboard_release import emit_startup_attestation

    for key, value in configured().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WOLF15_API_READ_ONLY_STARTUP", "true")
    monkeypatch.setenv("WOLF15_SERVICE_ROLE", "api")
    workers = dict.fromkeys(["outbox", "relay", "peer_health", "candle_aggregator", "orchestrator"], False)
    workers[background] = True
    with pytest.raises(ValueError, match="containment"):
        emit_startup_attestation(workers)


def test_release_config_is_explicit_and_has_no_predeploy() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "deploy/railway/owner-dashboard-api.json").read_text())
    assert config["deploy"]["startCommand"] == "python -m api.owner_dashboard_release"
    assert config["deploy"]["preDeployCommand"] == []
    assert config["deploy"]["restartPolicyType"] == "NEVER"
