"""Regression tests for pressure-decision family lineage (Phase 1).

Locks the taxonomy produced by ``_pressure_family_lineage`` so DecisionUpdate keeps
its origin instead of flattening every decision to the parent ``signal_family``.
Pure-function tests -- no pipeline/finalizer construction required.
"""

from __future__ import annotations

from analysis.signal_json_emitter import build_signal_json_event
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_lineage = WolfConstitutionalPipeline._pressure_family_lineage


def test_quorum_reached_maps_to_allowed_canary_quorum():
    out = _lineage(
        {"allowed_quorum": {"quorum_reached": True}},
        microboost_detected=False,
        resolved_family="NO_TRADE_PRESSURE_TELEMETRY_ONLY",
    )
    assert out["source_family"] == "ALLOWED_CANARY_QUORUM"
    assert out["source_stage"] == "SIGNAL_THROTTLE_INTEL"
    assert out["resolved_family"] == "NO_TRADE_PRESSURE_TELEMETRY_ONLY"
    assert out["family_lineage_version"] == 1


def test_microboost_repeated_phase():
    report = {"microboost_summary": {"latest": {"phase_unpriced": "REPEATED_MICROBOOST"}}}
    out = _lineage(report, microboost_detected=True, resolved_family="R")
    assert out["source_family"] == "REPEATED_MICROBOOST"
    assert out["source_stage"] == "MICROBOOST"


def test_microboost_ignition_phase():
    report = {"microboost_summary": {"latest": {"phase_unpriced": "IGNITION_MICROBOOST"}}}
    out = _lineage(report, microboost_detected=True, resolved_family="R")
    assert out["source_family"] == "IGNITION_MICROBOOST"


def test_microboost_near_gate_phase():
    report = {"microboost_summary": {"latest": {"phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST"}}}
    out = _lineage(report, microboost_detected=True, resolved_family="R")
    assert out["source_family"] == "NEAR_GATE_MICROBOOST"


def test_microboost_without_phase_defaults_pressure():
    out = _lineage({}, microboost_detected=True, resolved_family="R")
    assert out["source_family"] == "MICROBOOST_PRESSURE"
    assert out["source_stage"] == "MICROBOOST"


def test_ignition_watch_lifecycle():
    report = {"candidate_lifecycle": {"status": "LATEST_IGNITION_WATCH_ONLY"}}
    out = _lineage(report, microboost_detected=False, resolved_family="R")
    assert out["source_family"] == "IGNITION_WATCH"
    assert out["source_stage"] == "CANDIDATE_LIFECYCLE"


def test_pair_signal_candidate_lifecycle_maps_timing_block():
    report = {"candidate_lifecycle": {"status": "PAIR_SIGNAL_CANDIDATE_FROM_ROTATION_CONTEXT"}}
    out = _lineage(report, microboost_detected=False, resolved_family="R")
    assert out["source_family"] == "TIMING_BLOCK"
    assert out["source_stage"] == "CANDIDATE_LIFECYCLE"


def test_theme_pressure_phase():
    report = {"latest_phase": "THEME_PRESSURE"}
    out = _lineage(report, microboost_detected=False, resolved_family="R")
    assert out["source_family"] == "THEME_PRESSURE"
    assert out["source_stage"] == "PRESSURE_BLOCK"


def test_empty_report_falls_back_to_canary():
    out = _lineage({}, microboost_detected=False, resolved_family="NO_TRADE_PRESSURE_TELEMETRY_ONLY")
    assert out["source_family"] == "THROTTLE_PRESSURE_CANARY"
    assert out["source_stage"] == "SIGNAL_THROTTLE_INTEL"
    assert out["resolved_family"] == "NO_TRADE_PRESSURE_TELEMETRY_ONLY"


def test_priority_quorum_over_microboost():
    report = {
        "allowed_quorum": {"quorum_reached": True},
        "microboost_summary": {"latest": {"phase_unpriced": "REPEATED_MICROBOOST"}},
    }
    out = _lineage(report, microboost_detected=True, resolved_family="R")
    assert out["source_family"] == "ALLOWED_CANARY_QUORUM"  # quorum has priority


def test_handles_non_dict_report_fields_gracefully():
    # Defensive: malformed report should not raise and falls back to canary.
    report = {"allowed_quorum": None, "candidate_lifecycle": None, "microboost_summary": None}
    out = _lineage(report, microboost_detected=False, resolved_family="R")
    assert out["source_family"] == "THROTTLE_PRESSURE_CANARY"


def test_family_lineage_reason_present_and_matches_source():
    quorum = _lineage(
        {"allowed_quorum": {"quorum_reached": True}},
        microboost_detected=False,
        resolved_family="R",
    )
    assert quorum["family_lineage_reason"] == "allowed_quorum_reached_but_execution_quality_missing"

    canary = _lineage({}, microboost_detected=False, resolved_family="R")
    assert canary["family_lineage_reason"] == "throttle_pressure_canary_telemetry_only"

    # Every branch must carry a non-empty reason (no silent label-only output).
    repeated = _lineage(
        {"microboost_summary": {"latest": {"phase_unpriced": "REPEATED_MICROBOOST"}}},
        microboost_detected=True,
        resolved_family="R",
    )
    assert repeated["family_lineage_reason"]


# --------------------------------------------------------------------------- #
# End-to-end: lineage must SURVIVE the dict -> SignalJsonEvent -> emit rebuild
# (regression: it was computed default-ON but dropped before the log, 0/1484 live)
# --------------------------------------------------------------------------- #


def _decision_payload_with_lineage(**overrides):
    payload = {
        "event": "signal_decision_update_json",
        "symbol": "EURCAD",
        "signal_family": "SIGNAL_THROTTLE_PRESSURE",
        "status": "NO_TRADE_REASONED",
        "signal_valid_time_utc": "2026-06-16T07:00:00+00:00",
        "signal_valid_price": 1.5,
        "entry_reference_price": 1.5,
        "entry_zone": [1.5, 1.5],
        "raw_direction": "BUY",
        "source_family": "THROTTLE_PRESSURE_CANARY",
        "source_stage": "SIGNAL_THROTTLE_INTEL",
        "resolved_family": "NO_TRADE_PRESSURE_TELEMETRY_ONLY",
        "family_lineage_reason": "throttle_pressure_canary_telemetry_only",
    }
    payload.update(overrides)
    return payload


def test_lineage_survives_emission_round_trip():
    out = build_signal_json_event(_decision_payload_with_lineage()).to_dict()
    assert out["source_family"] == "THROTTLE_PRESSURE_CANARY"
    assert out["source_stage"] == "SIGNAL_THROTTLE_INTEL"
    assert out["resolved_family"] == "NO_TRADE_PRESSURE_TELEMETRY_ONLY"
    assert out["family_lineage_reason"] == "throttle_pressure_canary_telemetry_only"


def test_lineage_absent_emits_null_consistent_with_other_optionals():
    payload = _decision_payload_with_lineage()
    for k in ("source_family", "source_stage", "resolved_family", "family_lineage_reason"):
        payload.pop(k)
    out = build_signal_json_event(payload).to_dict()
    assert out["source_family"] is None
    assert out["resolved_family"] is None
