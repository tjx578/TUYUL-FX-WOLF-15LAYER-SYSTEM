"""Cache warmup evidence comes from the pipeline bus, never an API reconstruction."""

from typing import Any
from unittest.mock import Mock

import pytest

from context.live_context_bus import LiveContextBus
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from startup.analysis_loop import _build_degraded_verdict, _build_verdict_cache_payload
from state.governance_gate import GovernanceAction, GovernanceVerdict
from tests.test_pipeline_full_mock import _l3, _l11
from tests.test_pipeline_full_mock import mocked_pipeline as mocked_pipeline
from tests.test_pipeline_governance_cache_contract import (
    isolate_artifacts_and_external_io as isolate_artifacts_and_external_io,
)


@pytest.mark.parametrize(
    "path",
    ["allow", "reduced", "block", "hold", "neutral", "zero_sl", "missing_l6", "fatal", "warmup_failed", "safe_mode"],
)
def test_actual_bus_measurement_survives_pipeline_result_paths(
    mocked_pipeline: WolfConstitutionalPipeline, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # Independent bus has richer/synthetic histories even though no Redis read
    # is available. Use its actual check_warmup method, not a ready=True mock.
    bus = object.__new__(LiveContextBus)
    bus._init()
    for timeframe, minimum in mocked_pipeline.WARMUP_MIN_BARS.items():
        count = 0 if path == "warmup_failed" and timeframe == "H1" else minimum + 3
        bus.set_candle_history("EURUSD", timeframe, [{"close": float(i), "synthetic": True} for i in range(count)])
    checker = Mock(wraps=bus.check_warmup)
    monkeypatch.setattr(mocked_pipeline._context_bus, "check_warmup", checker)
    action = {
        "block": GovernanceAction.BLOCK,
        "hold": GovernanceAction.HOLD,
        "reduced": GovernanceAction.ALLOW_REDUCED,
    }.get(path, GovernanceAction.ALLOW)
    monkeypatch.setattr(
        mocked_pipeline, "_assess_governance", Mock(return_value=GovernanceVerdict(action=action, symbol="EURUSD"))
    )
    if path == "neutral":
        assert mocked_pipeline._l3 is not None
        mocked_pipeline._l3.analyze = Mock(return_value=_l3(trend="NEUTRAL", direction="HOLD"))
    elif path == "zero_sl":
        assert mocked_pipeline._l11 is not None
        mocked_pipeline._l11.calculate_rr = Mock(return_value=_l11(stop_loss=0.0))
    elif path == "missing_l6":
        monkeypatch.setattr(mocked_pipeline, "_l6", None)
    elif path == "fatal":
        monkeypatch.setattr(mocked_pipeline, "_build_l14_json", Mock(side_effect=RuntimeError("synthetic failure")))

    result = mocked_pipeline.execute("EURUSD", {"safe_mode": path == "safe_mode"})
    expected = None if path == "safe_mode" else path != "warmup_failed"
    assert result["warmup_measured"] is (path != "safe_mode")
    if path == "safe_mode":
        checker.assert_not_called()
    else:
        checker.assert_called_once_with("EURUSD", mocked_pipeline.WARMUP_MIN_BARS)
        assert result["warmup"]["ready"] is expected
    if path == "warmup_failed":
        assert result["verdict"] is None  # Preserve the no-persist abort signal.
    elif path == "fatal":
        assert any("FATAL_ERROR" in error for error in result["errors"])
    assert _build_verdict_cache_payload("EURUSD", result)["warmup_ready"] is expected


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ({}, None),
        ({"warmup": {"ready": True}}, None),
        ({"warmup_measured": False, "warmup": {"ready": True}}, None),
        ({"warmup_measured": 1, "warmup": {"ready": True}}, None),
        ({"warmup_measured": True, "warmup": {"ready": "true"}}, None),
        ({"warmup_measured": True, "warmup": {"ready": 1}}, None),
        ({"warmup_measured": True, "warmup": []}, None),
        ({"warmup_measured": True, "warmup": {"ready": True}}, True),
        ({"warmup_measured": True, "warmup": {"ready": False}}, False),
    ],
)
def test_cache_only_accepts_explicit_measured_boolean(evidence: dict[str, Any], expected: bool | None) -> None:
    assert _build_verdict_cache_payload("EURUSD", evidence)["warmup_ready"] is expected


@pytest.mark.parametrize("reason", ["PIPELINE_TIMEOUT:1s", "PIPELINE_ERROR:RuntimeError"])
def test_external_degraded_snapshot_has_no_warmup_measurement(reason: str) -> None:
    assert _build_degraded_verdict("EURUSD", reason).get("warmup_ready") is None
