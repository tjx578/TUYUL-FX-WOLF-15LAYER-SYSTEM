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
    for key in (
        "pressure_decision_count",
        "microboost_watch_count",
        "direction_missing_count",
        "inherited_direction_count",
        "pattern_resolved_count",
        "phase_ambiguous_count",
        "recent_conflict_count",
        "price_phase_conflict_count",
        "stale_intel_count",
    ):
        assert snap[key] == 0
    assert snap["microboost_direction_resolver_enabled"] is False
    assert snap["direction_inheritance_window_seconds"] == 600.0


def test_resolver_direction_source_counters():
    p = _pipeline()
    p._bump_family_counters({"status": "MICROBOOST_WATCH", "direction_source": "INHERITED_BUT_PHASE_AMBIGUOUS"})
    p._bump_family_counters({"status": "MICROBOOST_WATCH", "direction_source": "DIRECTION_CONFLICT_RECENT_INTEL"})
    p._bump_family_counters({"status": "MICROBOOST_WATCH", "direction_source": "DIRECTION_CONFLICT_PRICE_PHASE"})
    p._bump_family_counters({"status": "MICROBOOST_WATCH", "direction_source": "DIRECTION_STALE_INTEL"})
    snap = p.family_counters_snapshot()
    assert snap["phase_ambiguous_count"] == 1
    assert snap["inherited_direction_count"] == 1  # ambiguous is also inherited
    assert snap["recent_conflict_count"] == 1
    assert snap["price_phase_conflict_count"] == 1
    assert snap["stale_intel_count"] == 1
    assert snap["direction_missing_count"] == 0


def test_resolver_enabled_reflects_flag(monkeypatch):
    monkeypatch.setenv("MICROBOOST_DIRECTION_INHERIT_ENABLED", "true")
    assert _pipeline().family_counters_snapshot()["microboost_direction_resolver_enabled"] is True


def test_decision_update_bumps_pressure_decision():
    p = _pipeline()
    p._bump_family_counters({"event": "signal_decision_update_json", "final_direction": "WAIT"})
    assert p.family_counters_snapshot()["pressure_decision_count"] == 1


def test_watch_without_direction_bumps_direction_missing():
    p = _pipeline()
    p._bump_family_counters({"signal_family": "MICROBOOST_WATCH", "status": "MICROBOOST_WATCH", "raw_direction": None})
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
