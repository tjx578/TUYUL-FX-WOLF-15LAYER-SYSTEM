"""Ordinary analysis vetoes retain the real pre-analysis governance assessment."""

from unittest.mock import Mock

import pytest

from api.verdict_normalization import admission_state
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from startup.analysis_loop import _build_verdict_cache_payload
from state.governance_gate import GovernanceAction, GovernanceVerdict
from tests.test_pipeline_full_mock import _l2, _l3, _l11
from tests.test_pipeline_full_mock import mocked_pipeline as mocked_pipeline
from tests.test_pipeline_governance_cache_contract import (
    isolate_artifacts_and_external_io as isolate_artifacts_and_external_io,
)


@pytest.mark.parametrize("action", [GovernanceAction.ALLOW, GovernanceAction.ALLOW_REDUCED])
@pytest.mark.parametrize("exit_case", ["neutral", "direction_conflict", "zero_sl", "zero_tp"])
def test_ordinary_analysis_exit_preserves_assessed_admission(
    mocked_pipeline: WolfConstitutionalPipeline,
    monkeypatch: pytest.MonkeyPatch,
    action: GovernanceAction,
    exit_case: str,
) -> None:
    assessed = GovernanceVerdict(
        action=action, symbol="EURUSD", confidence_penalty=0.1 if action == GovernanceAction.ALLOW_REDUCED else 0.0
    )
    assessor = Mock(return_value=assessed)
    monkeypatch.setattr(mocked_pipeline, "_assess_governance", assessor)
    assert mocked_pipeline._l3 is not None
    assert mocked_pipeline._l2 is not None
    assert mocked_pipeline._l11 is not None
    if exit_case == "neutral":
        mocked_pipeline._l3.analyze = Mock(return_value=_l3(trend="NEUTRAL", direction="HOLD"))
        reason = "no_l3_direction"
    elif exit_case == "direction_conflict":
        mocked_pipeline._l2.analyze = Mock(return_value=_l2(htf_bias="BEARISH", direction="SELL"))
        reason = "direction_conflict"
    else:
        overrides = {"stop_loss": 0.0} if exit_case == "zero_sl" else {"take_profit_1": 0.0}
        mocked_pipeline._l11.calculate_rr = Mock(return_value=_l11(**overrides))
        reason = "sl_tp_zero"

    result = mocked_pipeline.execute("EURUSD")
    assessor.assert_called_once()
    assert result["l12_verdict"]["verdict"] == "NO_TRADE"
    assert result["l12_verdict"]["reason"] == reason
    assert not any("FATAL_ERROR" in error for error in result["errors"])
    assert result.get("governance") == assessed.to_dict()
    payload = _build_verdict_cache_payload("EURUSD", result)
    assert payload["verdict"] == "NO_TRADE"
    assert payload["governance"] == assessed.to_dict()
    assert admission_state(payload) == action.value


@pytest.mark.parametrize("action", [GovernanceAction.ALLOW, GovernanceAction.ALLOW_REDUCED])
def test_missing_analyzer_is_degraded_without_positive_admission(
    mocked_pipeline: WolfConstitutionalPipeline, monkeypatch: pytest.MonkeyPatch, action: GovernanceAction
) -> None:
    assessor = Mock(return_value=GovernanceVerdict(action=action, symbol="EURUSD"))
    monkeypatch.setattr(mocked_pipeline, "_assess_governance", assessor)
    monkeypatch.setattr(mocked_pipeline, "_l6", None)
    result = mocked_pipeline.execute("EURUSD")
    assessor.assert_called_once()
    assert "L6_ANALYZER_NOT_INITIALIZED" in result["errors"]
    assert "governance" not in result
    assert admission_state(_build_verdict_cache_payload("EURUSD", result)) is None
