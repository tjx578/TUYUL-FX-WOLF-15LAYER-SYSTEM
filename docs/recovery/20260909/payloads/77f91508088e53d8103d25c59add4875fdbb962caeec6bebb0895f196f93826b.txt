"""Regression gates for single-owner runtime orchestration."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from api import app_factory

ROOT = Path(__file__).resolve().parents[1]


def test_api_rejects_removed_embedded_orchestrator_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOLF15_EMBED_ORCHESTRATOR", "true")

    with pytest.raises(RuntimeError, match="sole runtime orchestration owner"):
        app_factory._assert_api_only_orchestrator_ownership()


def test_api_accepts_absent_or_explicitly_false_legacy_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WOLF15_EMBED_ORCHESTRATOR", raising=False)
    app_factory._assert_api_only_orchestrator_ownership()

    monkeypatch.setenv("WOLF15_EMBED_ORCHESTRATOR", "false")
    app_factory._assert_api_only_orchestrator_ownership()


def test_api_factory_has_no_autonomous_state_manager_constructor() -> None:
    source = inspect.getsource(app_factory)

    assert "StateManager().run_forever" not in source
    assert 'name="embedded-orchestrator"' not in source
    assert "Embedded orchestrator started" not in source
    assert "threading.Thread" not in source


def test_railway_manifests_bind_api_and_orchestrator_to_distinct_entrypoints() -> None:
    api_manifest = (ROOT / "railway.toml").read_text(encoding="utf-8")
    orchestrator_manifest = (ROOT / "railway-orchestrator.toml").read_text(encoding="utf-8")

    assert 'startCommand = "bash deploy/railway/start_api.sh"' in api_manifest
    assert "start_api_consolidated.sh" not in api_manifest
    assert 'startCommand = "bash deploy/railway/start_orchestrator.sh"' in orchestrator_manifest


def test_api_startup_scripts_never_enable_embedded_orchestrator() -> None:
    for relative in ("deploy/railway/start_api.sh", "deploy/railway/start_api_consolidated.sh"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'WOLF15_EMBED_ORCHESTRATOR="true"' not in source
        assert "WOLF15_EMBED_ORCHESTRATOR" in source
        assert "is no longer supported" in source


def test_standalone_entrypoint_remains_the_only_state_manager_launcher() -> None:
    orchestrator = (ROOT / "deploy/railway/start_orchestrator.sh").read_text(encoding="utf-8")
    assert "exec python -m services.orchestrator.state_manager" in orchestrator

    api = (ROOT / "deploy/railway/start_api.sh").read_text(encoding="utf-8")
    compatibility = (ROOT / "deploy/railway/start_api_consolidated.sh").read_text(encoding="utf-8")
    assert "services.orchestrator.state_manager" not in api
    assert "services.orchestrator.state_manager" not in compatibility
