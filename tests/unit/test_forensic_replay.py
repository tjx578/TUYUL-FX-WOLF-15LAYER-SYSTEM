from __future__ import annotations

import json
from pathlib import Path

from journal.forensic_replay import (
    MINIMUM_REPLAY_ARTIFACTS,
    append_replay_artifact,
    reconstruct_incident,
)


def _append_audit_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def test_reconstruct_incident_reports_complete_coverage(tmp_path: Path) -> None:
    artifact_log = tmp_path / "artifacts.jsonl"
    audit_log = tmp_path / "audit.jsonl"
    cid = "ei_complete_001"

    for artifact_type in MINIMUM_REPLAY_ARTIFACTS:
        append_replay_artifact(
            artifact_type,
            correlation_id=cid,
            payload={"artifact_type": artifact_type},
            log_path=artifact_log,
        )

    _append_audit_line(
        audit_log,
        {
            "timestamp": "2026-03-20T12:00:00+00:00",
            "action": "ORDER_PLACED",
            "resource": f"intent:{cid}",
            "details": {"execution_intent_id": cid},
        },
    )

    report = reconstruct_incident(cid, artifact_log_path=artifact_log, audit_log_path=audit_log)

    assert report["coverage"]["is_sufficient"] is True
    assert report["coverage"]["missing"] == []
    assert report["artifact_count"] == len(MINIMUM_REPLAY_ARTIFACTS)
    assert report["audit_count"] == 1
    assert len(report["timeline"]) >= len(MINIMUM_REPLAY_ARTIFACTS)


def test_reconstruct_incident_reports_missing_artifacts(tmp_path: Path) -> None:
    artifact_log = tmp_path / "artifacts.jsonl"
    cid = "ei_partial_001"

    append_replay_artifact(
        "verdict_provenance",
        correlation_id=cid,
        payload={"verdict": "EXECUTE"},
        log_path=artifact_log,
    )

    report = reconstruct_incident(cid, artifact_log_path=artifact_log, audit_log_path=tmp_path / "none.jsonl")

    assert report["coverage"]["is_sufficient"] is False
    assert "event_history" in report["coverage"]["missing"]
    assert "execution_lifecycle" in report["coverage"]["missing"]
