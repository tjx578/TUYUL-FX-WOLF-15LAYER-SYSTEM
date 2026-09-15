from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

GRANTED_AT = datetime(2026, 8, 3, 11, 5, tzinfo=UTC)


def _grant() -> dict[str, object]:
    return {
        "pair_admission_id": "5scr-admission:" + "a" * 32,
        "symbol": "EURUSD",
        "status": "GRANTED",
        "granted_at_utc": GRANTED_AT.isoformat(),
        "expires_at_utc": (GRANTED_AT + timedelta(minutes=15)).isoformat(),
    }


def _report(as_of: datetime | None) -> dict[str, object]:
    report: dict[str, object] = {"pair_admission_grants": [_grant()]}
    if as_of is not None:
        report["data_quality"] = {"end_utc": as_of.isoformat()}
    return report


def test_runtime_selects_only_an_active_pair_admission() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(GRANTED_AT + timedelta(minutes=5)),
    )

    assert selected["pair_admission_id"] == "5scr-admission:" + "a" * 32


def test_runtime_rejects_expired_pair_admission() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(GRANTED_AT + timedelta(minutes=15)),
    )

    assert selected == {}


def test_runtime_fails_closed_without_an_as_of_timestamp() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(None),
    )

    assert selected == {}


def test_pressure_payload_carries_complete_rejection_audit_and_deterministic_hash() -> None:
    evaluation = {
        "event": "pair_admission_evaluated",
        "evaluation_id": "5scr-admission-evaluation:" + "a" * 32,
        "rule_version": "5scr.pair-admission.raw-ledger.v2",
        "candidate_block_id": "5scr-admission-candidate:" + "b" * 32,
        "symbol": "EURUSD",
        "decision": "REJECTED",
        "rejection_reason": "RAW_LEDGER_GAP_EXCEEDED",
        "reason_codes": ["RAW_LEDGER_GAP_EXCEEDED"],
        "calculated_duration_seconds": 601.0,
        "calculated_max_gap_seconds": 301.0,
        "execution_authority": False,
    }
    report: dict[str, object] = {
        "pair_admission_grants": [],
        "pair_admission_summary": {
            "rule_version": "5scr.pair-admission.raw-ledger.v2",
            "evaluated_blocks": 1,
            "granted_blocks": 0,
            "rejected_blocks": 1,
            "grant_rate": 0.0,
            "rejection_counts": {"RAW_LEDGER_GAP_EXCEEDED": 1},
            "evaluations": [evaluation],
        },
        "data_quality": {"end_utc": "2026-08-03T11:10:00+00:00"},
    }
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)

    first = pipeline._pressure_observability_fields(
        symbol="EURUSD",
        report=report,
        pressure_event_count=3,
    )
    second = pipeline._pressure_observability_fields(
        symbol="EURUSD",
        report=report,
        pressure_event_count=3,
    )

    assert first["pair_admission_evaluation"] == evaluation
    assert first["pair_admission_evaluation_hash"].startswith("sha256:")
    assert first["pair_admission_evaluation_hash"] == second["pair_admission_evaluation_hash"]
    assert first["pair_admission_audit_persistence_target"] == "pressure_radar_events.payload"
    assert first["pair_eligible_for_analysis"] is False


def test_mature_advisory_pressure_without_raw_authority_is_not_a_missed_evaluation() -> None:
    report: dict[str, object] = {
        "pair_admission_grants": [],
        "pair_admission_summary": {
            "rule_version": "5scr.pair-admission.raw-ledger.v2",
            "evaluated_blocks": 0,
            "granted_blocks": 0,
            "rejected_blocks": 0,
            "evaluations": [],
        },
        "raw_admission_blocks": [],
        "raw_admission_population": {
            "population_status": "NO_RAW_AUTHORITY_CANDIDATE",
            "raw_authority_event_count": 0,
        },
        "runtime_config": {"min_clean_block_minutes": 5.0},
        "symbol_activity": {
            "USDCHF": {
                "latest_block_duration_seconds": 3040.073,
                "latest_block_effective_ticks": 1499,
                "latest_block_events": 1499,
            }
        },
        "data_quality": {"end_utc": "2026-08-17T06:51:45+00:00"},
    }
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)

    fields = pipeline._pressure_observability_fields(
        symbol="USDCHF",
        report=report,
        pressure_event_count=1499,
    )

    assert fields["pair_admission_decision"] == "NOT_EVALUATED"
    assert fields["pair_admission_evaluation_required"] is False
    assert fields["pair_admission_evaluation_complete"] is True
    assert fields["pair_admission_evaluation_coverage_status"] == "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK"
    assert fields["pair_admission_evaluation_missing_incident"] is False
    assert fields["pair_admission_raw_replay_required"] is False
    assert fields["pair_admission_advisory_block_status"] == "MATURE_ADVISORY_ONLY_NON_AUTHORITATIVE"
    assert fields["pair_admission_advisory_pressure_is_authority"] is False
    assert fields["pair_admission_symbol_monitoring"]["evaluated_blocks"] == 0


def test_raw_authority_block_without_evaluation_is_reported_as_incident() -> None:
    report: dict[str, object] = {
        "pair_admission_grants": [],
        "pair_admission_summary": {"evaluations": []},
        "raw_admission_blocks": [
            {
                "raw_block_id": "5scr-raw-block:" + "b" * 32,
                "symbol": "USDCHF",
                "start": "2026-08-17T06:00:00+00:00",
                "end": "2026-08-17T06:05:00+00:00",
                "duration_seconds": 300.0,
                "effective_ticks": 48,
                "evaluation_state": "ACTIVE",
            }
        ],
        "raw_admission_population": {
            "population_status": "RAW_AUTHORITY_CANDIDATES_AVAILABLE",
            "raw_authority_event_count": 48,
        },
        "symbol_activity": {
            "USDCHF": {
                "latest_block_duration_seconds": 300.0,
                "latest_block_effective_ticks": 48,
                "latest_block_events": 48,
            }
        },
        "data_quality": {"end_utc": "2026-08-17T06:05:00+00:00"},
    }
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)

    fields = pipeline._pressure_observability_fields(
        symbol="USDCHF",
        report=report,
        pressure_event_count=48,
    )

    assert fields["pair_admission_evaluation_required"] is True
    assert fields["pair_admission_evaluation_complete"] is False
    assert fields["pair_admission_evaluation_coverage_status"] == "MISSING_EVALUATION_INCIDENT"
    assert fields["pair_admission_evaluation_missing_incident"] is True
    assert fields["pair_admission_raw_replay_required"] is True
    assert fields["pair_admission_latest_raw_block_id"] == "5scr-raw-block:" + "b" * 32
    assert fields["pair_admission_raw_authority_event_count"] == 48
