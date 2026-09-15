"""Actual pipeline results carry assessed admission through cache projection."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from api.verdict_normalization import admission_state
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from startup.analysis_loop import _build_degraded_verdict, _build_verdict_cache_payload
from state.governance_gate import GovernanceAction, GovernanceVerdict
from tests.test_pipeline_full_mock import mocked_pipeline as mocked_pipeline


@pytest.fixture(autouse=True)
def isolate_artifacts_and_external_io(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("journal.forensic_replay.FORENSIC_ARTIFACTS_PATH", tmp_path / "replay.jsonl")
    monkeypatch.setattr("storage.trade_archive._from_redis", lambda *args: [])
    monkeypatch.setattr("storage.trade_archive._from_postgres", lambda *args: [])
    monkeypatch.setattr("redis.Redis.execute_command", Mock(side_effect=AssertionError("External Redis forbidden")))


@pytest.mark.parametrize("action", [GovernanceAction.ALLOW, GovernanceAction.ALLOW_REDUCED])
def test_successful_pipeline_persists_assessed_admission(
    mocked_pipeline: WolfConstitutionalPipeline, monkeypatch: pytest.MonkeyPatch, action: GovernanceAction
) -> None:
    assessed = GovernanceVerdict(
        action=action,
        symbol="EURUSD",
        confidence_penalty=0.1 if action == GovernanceAction.ALLOW_REDUCED else 0.0,
        reasons=("synthetic_assessed_state",),
    )
    assess = Mock(return_value=assessed)
    monkeypatch.setattr(mocked_pipeline, "_assess_governance", assess)

    result = mocked_pipeline.execute("EURUSD")
    assert result["execution_map"]["halt_reason"] is None, result["errors"]
    assess.assert_called_once()
    assert result.get("governance") == assessed.to_dict()
    payload = _build_verdict_cache_payload("EURUSD", result)
    assert payload["governance"] == assessed.to_dict()
    assert admission_state(payload) == action.value


@pytest.mark.parametrize("action", [GovernanceAction.BLOCK, GovernanceAction.HOLD])
def test_rejected_pipeline_keeps_assessed_admission(
    mocked_pipeline: WolfConstitutionalPipeline, monkeypatch: pytest.MonkeyPatch, action: GovernanceAction
) -> None:
    assessed = GovernanceVerdict(action=action, symbol="EURUSD", reasons=("synthetic_rejection",))
    monkeypatch.setattr(mocked_pipeline, "_assess_governance", Mock(return_value=assessed))
    result = mocked_pipeline.execute("EURUSD")
    assert result["governance"] == assessed.to_dict()
    assert admission_state(_build_verdict_cache_payload("EURUSD", result)) == action.value


@pytest.mark.parametrize("reason", ["PIPELINE_TIMEOUT:1s", "PIPELINE_ERROR:RuntimeError"])
def test_degraded_cache_does_not_manufacture_admission(reason: str) -> None:
    assert admission_state(_build_degraded_verdict("EURUSD", reason)) is None


def test_failed_pipeline_does_not_export_positive_admission(
    mocked_pipeline: WolfConstitutionalPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    assessed = GovernanceVerdict(action=GovernanceAction.ALLOW, symbol="EURUSD")
    monkeypatch.setattr(mocked_pipeline, "_assess_governance", Mock(return_value=assessed))
    monkeypatch.setattr(
        mocked_pipeline, "_build_l14_json", Mock(side_effect=RuntimeError("synthetic assembly failure"))
    )
    result = mocked_pipeline.execute("EURUSD")
    assert any("FATAL_ERROR" in error for error in result["errors"])
    assert "governance" not in result
    assert admission_state(_build_verdict_cache_payload("EURUSD", result)) is None
