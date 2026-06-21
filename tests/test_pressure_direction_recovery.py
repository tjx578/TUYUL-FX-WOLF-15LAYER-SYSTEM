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

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer
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
    cast(Any, pipe)._signal_throttle_live_analyzer = analyzer
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


# --- P2D': diagnostics-source recovery (flag-guarded, default OFF) ---------------


def _hold_with_sources(sources: dict, conflicts: list | None = None) -> dict:
    """A synthesis whose execution.direction has collapsed to HOLD but whose
    per-layer biases survive in direction_diagnostics.sources."""
    return {
        "execution": {
            "direction": "HOLD",
            "direction_diagnostics": {
                "conflicts": conflicts or [],
                "sources": sources,
            },
        }
    }


def test_diagnostics_recovery_recovers_from_l3_when_execution_hold(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": None, "l2": None, "l3": "BUY", "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={"verdict": "HOLD"}, synthesis=synthesis, source_verdict=None
        )
        == "BUY"
    )


def test_diagnostics_recovery_no_l3_lower_layers_agree(monkeypatch):
    """no_l3_direction collapse: l3 is None but l2+l1 agree -> recover."""
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": "SELL", "l2": "SELL", "l3": None, "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=synthesis, source_verdict=None
        )
        == "SELL"
    )


def test_diagnostics_recovery_conflict_returns_none(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": None, "l2": "SELL", "l3": "BUY", "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=synthesis, source_verdict=None
        )
        is None
    )


def test_diagnostics_recovery_bails_on_recorded_conflicts(monkeypatch):
    """Even if sources are unanimous, a pre-recorded resolver conflict blocks recovery."""
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources(
        {"l1": "BUY", "l2": "BUY", "l3": "BUY", "l9": "BUY"}, conflicts=["L2_HTF_MTA"]
    )
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=synthesis, source_verdict=None
        )
        is None
    )


def test_diagnostics_recovery_disabled_by_subflag_default_off(monkeypatch):
    monkeypatch.delenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", raising=False)
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": None, "l2": None, "l3": "BUY", "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=synthesis, source_verdict=None
        )
        is None
    )


def test_diagnostics_recovery_respects_c2_master_kill_switch(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY", "false")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": None, "l2": None, "l3": "BUY", "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={}, synthesis=synthesis, source_verdict=None
        )
        is None
    )


def test_diagnostics_recovery_does_not_override_primary_direction(monkeypatch):
    """A valid primary source wins; diagnostics are never consulted (no override)."""
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = _hold_with_sources({"l1": None, "l2": None, "l3": "SELL", "l9": None})
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={"direction": "BUY"}, synthesis=synthesis, source_verdict=None
        )
        == "BUY"
    )


def test_diagnostics_recovery_skipped_on_primary_conflict(monkeypatch):
    """A genuine primary-source conflict stays None; diagnostics do not rescue it."""
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, _ = _pipeline()
    synthesis = {
        "execution": {
            "direction": "SELL",
            "direction_diagnostics": {"conflicts": [], "sources": {"l3": "BUY"}},
        }
    }
    assert (
        pipe._resolve_pressure_observation_direction(
            l12_verdict={"direction": "BUY"}, synthesis=synthesis, source_verdict=None
        )
        is None
    )


def test_non_execute_canary_recovers_direction_from_diagnostics(monkeypatch):
    """End-to-end: HOLD-collapsed execution + surviving l3 bias seeds the canary
    raw_direction -- and stays classification-only (no downgraded/execute path)."""
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    pipe, analyzer = _pipeline()
    pipe._record_signal_throttle_downgrade_observation(
        symbol="NZDCHF",
        l12_verdict={"verdict": "HOLD"},
        legacy_verdict=None,
        reason="non_execute_verdict",
        synthesis=_hold_with_sources({"l1": None, "l2": None, "l3": "BUY", "l9": None}),
    )
    assert len(analyzer.canary) == 1
    assert analyzer.canary[0]["direction"] == "BUY"
    assert analyzer.canary[0]["direction_source"] == "DIRECTION_DIAGNOSTICS"
    assert analyzer.canary[0]["direction_confidence"] == "MEDIUM"
    assert analyzer.downgraded == []


# --- Root#1/case-c: SignalThrottleIntel -> pressure canary bridge ----------------


def test_intel_direction_bridge_default_off(monkeypatch):
    monkeypatch.delenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", raising=False)
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=None,
            source_verdict=None,
        )
        is None
    )


def test_intel_direction_bridge_recovers_same_symbol_direction(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=None,
            source_verdict=None,
        )
        == "BUY"
    )


def test_non_execute_canary_carries_intel_bridge_direction(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, analyzer = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "CANARY_QUORUM_PENDING_VALIDATION"},
    )

    pipe._record_signal_throttle_downgrade_observation(
        symbol="AUDCAD",
        l12_verdict={"verdict": "HOLD"},
        legacy_verdict=None,
        reason="non_execute_verdict",
        synthesis={"execution": {"direction": "HOLD"}},
    )

    assert len(analyzer.canary) == 1
    assert analyzer.canary[0]["direction"] == "BUY"
    assert analyzer.canary[0]["direction_source"] == "SIGNAL_THROTTLE_INTEL_CACHE"
    assert analyzer.canary[0]["direction_confidence"] in {"HIGH", "MEDIUM"}
    assert analyzer.canary[0]["direction_inherited"] is True
    assert analyzer.canary[0]["inherited_direction"] == "BUY"
    assert analyzer.canary[0]["inherited_direction_age_seconds"] >= 0
    assert analyzer.downgraded == []


def test_intel_bridge_direction_reaches_microboost_summary(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    real_analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC)

    class _TimestampedAnalyzer:
        def __init__(self) -> None:
            self.calls = 0
            self.downgraded: list[dict] = []

        def record_pressure_canary(self, **kwargs) -> None:
            kwargs["timestamp"] = base + timedelta(seconds=self.calls * 5)
            self.calls += 1
            real_analyzer.record_pressure_canary(**kwargs)

        def record_downgraded(self, **kwargs) -> None:
            self.downgraded.append(kwargs)

    adapter = _TimestampedAnalyzer()
    cast(Any, pipe)._signal_throttle_live_analyzer = adapter
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    for _ in range(5):
        pipe._record_signal_throttle_downgrade_observation(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            legacy_verdict=None,
            reason="non_execute_verdict",
            synthesis={"execution": {"direction": "HOLD"}},
        )

    latest = real_analyzer.snapshot()["microboost_summary"]["latest"]
    direction_recovery = real_analyzer.snapshot()["direction_recovery"]
    assert latest is not None
    assert latest["symbol"] == "AUDCAD"
    assert latest["direction"] == "BUY"
    assert latest["direction_source"] == "SIGNAL_THROTTLE_INTEL_CACHE"
    assert latest["direction_confidence"] in {"HIGH", "MEDIUM"}
    assert latest["direction_inherited"] is True
    assert latest["inherited_direction"] == "BUY"
    assert latest["inherited_direction_age_seconds"] >= 0
    assert direction_recovery["pressure_canary_direction_recovered_count"] == 5
    assert direction_recovery["microboost_raw_direction_recovered_count"] == 1
    assert adapter.downgraded == []


def test_intel_direction_bridge_ignores_other_symbol(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="EURCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=None,
            source_verdict=None,
        )
        is None
    )


def test_intel_direction_bridge_rejects_stale_cache(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", "60")
    pipe, _ = _pipeline()
    pipe._signal_throttle_intel_direction_cache = {
        "AUDCAD": ("BUY", datetime.now(UTC) - timedelta(seconds=120)),
    }

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=None,
            source_verdict=None,
        )
        is None
    )
    assert "AUDCAD" not in pipe._signal_throttle_intel_direction_cache


def test_intel_direction_bridge_does_not_override_primary_conflict(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"raw_direction": "BUY"},
            synthesis={"execution": {"direction": "SELL"}},
            source_verdict=None,
        )
        is None
    )


def test_intel_direction_bridge_blocks_on_current_diagnostics_conflict(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "WAIT", "direction_status": "ALLOWED_CANDIDATE"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=_hold_with_sources({"l1": "BUY", "l2": "SELL", "l3": None, "l9": None}),
            source_verdict=None,
        )
        is None
    )


def test_intel_direction_bridge_does_not_cache_mismatch_intel(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "true")
    pipe, _ = _pipeline()
    pipe._cache_signal_throttle_intel_direction(
        "AUDCAD",
        {"raw_direction": "BUY", "final_direction": "BLOCK_DIRECTION", "direction_status": "DIRECTION_MISMATCH"},
    )

    assert (
        pipe._resolve_pressure_observation_direction(
            symbol="AUDCAD",
            l12_verdict={"verdict": "HOLD"},
            synthesis=None,
            source_verdict=None,
        )
        is None
    )
