"""C2 - restore raw-direction propagation for non-execute pressure observations.

Guarded, classification-only fix. Before this, a non-execute pressure canary was
recorded with direction=None, starving the microboost counter engine and collapsing
watches to raw_direction_missing MICROBOOST_WATCH. When an upstream current-tick
source carries the raw direction, it must seed the recorded canary so BUY-at-resistance
can classify as a SELL absorption watch (the 27 May golden behavior).

Contract: restore direction propagation, NOT execution permission. The recovered
direction only seeds raw_direction on the pressure canary; it never sets
final_direction / valid_for_execution and never emits a SignalJSON.
"""
from __future__ import annotations

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


class _CapturingAnalyzer:
    def __init__(self) -> None:
        self.canary: list[dict] = []
        self.downgraded: list[dict] = []

    def record_pressure_canary(self, **kwargs) -> None:
        self.canary.append(kwargs)

    def record_downgraded(self, **kwargs) -> None:
        self.downgraded.append(kwargs)


def _pipeline():
    pipe = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    analyzer = _CapturingAnalyzer()
    pipe._signal_throttle_live_analyzer = analyzer
    return pipe, analyzer


# --- resolver: priority sources -------------------------------------------------


def test_resolver_recovers_from_synthesis_execution_direction():
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis={"execution": {"direction": "BUY"}}, source_verdict=None
        )
        == "BUY"
    )


def test_resolver_recovers_from_intel_raw_direction():
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={"signal_throttle_intel": {"raw_direction": "SELL"}},
            synthesis=None,
            source_verdict=None,
        )
        == "SELL"
    )


def test_resolver_recovers_from_downgraded_execute_verdict():
    """The pre-downgrade verdict (e.g. throttled_from) still carries the side."""
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=None, source_verdict="EXECUTE_REDUCED_RISK_BUY"
        )
        == "BUY"
    )


# --- resolver: safety guards ----------------------------------------------------


def test_resolver_returns_none_on_conflict():
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={"raw_direction": "BUY"},
            synthesis={"execution": {"direction": "SELL"}},
            source_verdict=None,
        )
        is None
    )


def test_resolver_returns_none_when_absent():
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(l12_verdict={}, synthesis=None, source_verdict=None)
        is None
    )


def test_resolver_disabled_by_kill_switch(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY", "false")
    pipe, _ = _pipeline()
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis={"execution": {"direction": "BUY"}}, source_verdict=None
        )
        is None
    )


# --- end-to-end record propagation ---------------------------------------------


def test_non_execute_canary_carries_recovered_direction():
    pipe, analyzer = _pipeline()
    pipe._record_signal_throttle_downgrade_observation(
        symbol="NZDCHF",
        l12_verdict={"verdict": "HOLD"},
        legacy_verdict=None,
        reason="non_execute_verdict",
        synthesis={"execution": {"direction": "BUY"}},
    )
    assert len(analyzer.canary) == 1
    assert analyzer.canary[0]["symbol"] == "NZDCHF"
    assert analyzer.canary[0]["direction"] == "BUY"


def test_non_execute_canary_stays_none_when_no_direction():
    """Anti-conflict / absent: behavior unchanged -- raw_direction_missing still allowed."""
    pipe, analyzer = _pipeline()
    pipe._record_signal_throttle_downgrade_observation(
        symbol="NZDCHF",
        l12_verdict={"verdict": "HOLD"},
        legacy_verdict=None,
        reason="non_execute_verdict",
        synthesis=None,
    )
    assert len(analyzer.canary) == 1
    assert analyzer.canary[0]["direction"] is None
