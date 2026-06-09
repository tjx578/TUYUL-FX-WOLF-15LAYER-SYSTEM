"""Tests for family/direction deploy-validation counters (Step 4).

In-memory counters, no added log volume. Constructed via ``__new__`` so no full
pipeline init is required.
"""

from __future__ import annotations

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def _pipeline() -> WolfConstitutionalPipeline:
    return WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)


def test_snapshot_defaults_zero():
    snap = _pipeline().family_counters_snapshot()
    assert snap == {
        "pressure_decision_count": 0,
        "microboost_watch_count": 0,
        "direction_missing_count": 0,
        "inherited_direction_count": 0,
        "pattern_resolved_count": 0,
    }


def test_decision_update_bumps_pressure_decision():
    p = _pipeline()
    p._bump_family_counters({"event": "signal_decision_update_json", "final_direction": "WAIT"})
    assert p.family_counters_snapshot()["pressure_decision_count"] == 1


def test_watch_without_direction_bumps_direction_missing():
    p = _pipeline()
    p._bump_family_counters(
        {"signal_family": "MICROBOOST_WATCH", "status": "MICROBOOST_WATCH", "raw_direction": None}
    )
    snap = p.family_counters_snapshot()
    assert snap["microboost_watch_count"] == 1
    assert snap["direction_missing_count"] == 1
    assert snap["inherited_direction_count"] == 0


def test_inherited_direction_counts_inherited_not_missing():
    p = _pipeline()
    p._bump_family_counters(
        {
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "direction_source": "INHERITED_FROM_PRESSURE_INTEL",
        }
    )
    snap = p.family_counters_snapshot()
    assert snap["inherited_direction_count"] == 1
    assert snap["direction_missing_count"] == 0


def test_final_direction_bumps_pattern_resolved():
    p = _pipeline()
    p._bump_family_counters(
        {"event": "signal_json", "status": "BUY_TIMING_VALID", "final_direction": "BUY", "valid_for_execution": True}
    )
    snap = p.family_counters_snapshot()
    assert snap["pattern_resolved_count"] == 1
    assert snap["pressure_decision_count"] == 0


def test_flag_off_disables_counting(monkeypatch):
    monkeypatch.setenv("SIGNAL_FAMILY_COUNTERS_ENABLED", "false")
    p = _pipeline()
    p._bump_family_counters({"event": "signal_decision_update_json"})
    assert p.family_counters_snapshot()["pressure_decision_count"] == 0


def test_accumulates_across_calls():
    p = _pipeline()
    for _ in range(3):
        p._bump_family_counters({"event": "signal_decision_update_json"})
    assert p.family_counters_snapshot()["pressure_decision_count"] == 3


def test_non_dict_payload_is_ignored():
    p = _pipeline()
    p._bump_family_counters(None)  # type: ignore[arg-type]
    assert p.family_counters_snapshot()["pressure_decision_count"] == 0
