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
