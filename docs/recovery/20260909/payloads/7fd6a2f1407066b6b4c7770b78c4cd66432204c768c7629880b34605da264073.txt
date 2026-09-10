from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent, analyze_signal_throttle_events
from analysis.strategy_5scr_pair_activity import pair_activity_ledger_hash
from analysis.strategy_5scr_pair_activity_report import PairActivityReportContextV31, build_pair_activity_report
from contracts.strategy_5scr_pair_activity import PairActivityAuditV31, PairActivityPolicyV31, RawActivityCoverageV31
from contracts.strategy_5scr_pair_admission import PairAdmissionGrant
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

START = datetime(2026, 9, 9, tzinfo=UTC)


def events() -> list[SignalThrottleLogEvent]:
    return [
        SignalThrottleLogEvent(
            timestamp=START + timedelta(seconds=second),
            severity="info",
            message="fixture only",
            symbol="EURUSD",
            event_type="ALLOWED",
            verdict=f"EXECUTE_{direction}",
            direction=direction,
            pressure_source="SignalThrottle",
            source_stream="ALLOWED",
            deployment_id="fixture-deployment",
            scanner_cycle_id=f"fixture-cycle-{second}",
            eligible_for_pressure_block=True,
            eligible_for_execution=False,
        )
        for second, direction in [(0, "BUY"), (150, "SELL"), (300, "BUY")]
    ]


def context(raw: list[SignalThrottleLogEvent], *, status: str = "COMPLETE") -> PairActivityReportContextV31:
    return PairActivityReportContextV31(
        coverage=RawActivityCoverageV31(
            status=status,
            ledger_id="fixture-complete-ledger",
            deployment_id="fixture-deployment",
            window_start_utc=START,
            window_end_utc=START + timedelta(seconds=300),
            source_ledger_hash=pair_activity_ledger_hash(raw),
        ),
        policy=PairActivityPolicyV31(
            policy_id="fixture-only-gap-150-ttl-600", maximum_source_gap_seconds=150, grant_ttl_seconds=600
        ),
        decision_at_utc=START + timedelta(seconds=300),
    )


def pipeline_fields(report: dict) -> dict:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    return pipeline._pressure_observability_fields(symbol="EURUSD", report=report, pressure_event_count=3)


def test_analyzer_keeps_mixed_direction_activity_without_promoting_legacy_grant() -> None:
    raw = events()
    report = analyze_signal_throttle_events(raw, pair_activity_context=context(raw))
    activity = report["pair_activity_v31"]["audit"]["evaluations"]
    assert len(activity) == 1
    assert activity[0]["duration_seconds"] == 300
    assert activity[0]["decision"] == "GRANTED"
    assert activity[0]["direction_quality"] == "CONFLICT"
    fields = pipeline_fields(report)
    assert fields["pair_activity_v31"]["evaluations"] == activity
    assert fields["pair_eligible_for_analysis"] is False
    assert fields["pair_admission_grant"] is None
    for name in ("hypothesis_authority", "risk_authority", "execution_authority", "valid_for_execution"):
        assert activity[0][name] is False
    with pytest.raises(ValidationError):
        PairAdmissionGrant.model_validate(activity[0])


def test_process_buffer_without_bound_context_stays_unbound() -> None:
    report = analyze_signal_throttle_events(events())
    assert report["pair_activity_v31"]["status"] == "UNBOUND"
    assert pipeline_fields(report)["pair_activity_v31"]["evaluations"] == []


@pytest.mark.parametrize("status", ["INCOMPLETE", "UNKNOWN"])
def test_unverified_coverage_preserves_activity_but_cannot_grant(status: str) -> None:
    raw = events()
    report = analyze_signal_throttle_events(raw, pair_activity_context=context(raw, status=status))
    rows = report["pair_activity_v31"]["audit"]["evaluations"]
    assert len(rows) == 1 and rows[0]["duration_seconds"] == 300
    assert rows[0]["decision"] == "SUSPENDED"
    assert rows[0]["admission_id"] is None


def test_pipeline_rejects_tampered_direction_quality_receipt() -> None:
    raw = events()
    report = analyze_signal_throttle_events(raw, pair_activity_context=context(raw))
    changed = deepcopy(report)
    changed["pair_activity_v31"]["audit"]["evaluations"][0]["direction_quality"] = "BUY"
    fields = pipeline_fields(changed)
    assert fields["pair_activity_v31"]["status"] == "INVALID_RECEIPT"
    assert fields["pair_admission_grant"] is None


def test_snapshot_replays_in_new_python_process_without_identity_change(tmp_path: Path) -> None:
    raw = events()
    first = build_pair_activity_report(raw, context=context(raw))
    snapshot = tmp_path / "activity.json"
    snapshot.write_text(json.dumps(first["audit"]), encoding="utf-8")
    restored = PairActivityAuditV31.model_validate_json(snapshot.read_text(encoding="utf-8"))
    request = tmp_path / "replay.json"
    bound = context(raw).model_dump(mode="json")
    bound["previous_evaluations"] = [item.model_dump(mode="json") for item in restored.evaluations]
    request.write_text(
        json.dumps({"events": [asdict(item) for item in raw], "context": bound}, default=str), encoding="utf-8"
    )
    program = (
        "import json,sys; from analysis.strategy_5scr_pair_activity_report import build_pair_activity_report; "
        "data=json.load(open(sys.argv[1],encoding='utf-8')); "
        "print(json.dumps(build_pair_activity_report(data['events'],context=data['context'])))"
    )
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LOCALAPPDATA",
        "APPDATA",
        "USERPROFILE",
        "COMSPEC",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, "-c", program, str(request)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    replayed = json.loads(result.stdout)
    assert replayed == first
