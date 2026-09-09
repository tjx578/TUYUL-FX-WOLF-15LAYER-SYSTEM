"""Read-only replay validation; consistency is separate from reader attestation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ops.mt5_mcp import account_binding, reconcile
from ops.mt5_mcp.report_integrity import evidence_digest, verify_report_integrity


def verify_reconciliation_replay(
    report: dict[str, Any],
    *,
    database: dict[str, Any],
    broker: dict[str, Any],
    expected_receipt_digest: str,
    expected_account_identifier: str,
    expected_sources: dict[str, str],
    window_from: datetime,
    window_to: datetime,
    as_of: datetime,
    maximum_age: timedelta,
) -> dict[str, Any]:
    """Replay retained inputs under caller-bound scope; never authorizes execution.

    Expected digest, account, sources, clock and age limit must be supplied by
    the verifier's caller, not copied from untrusted report fields.
    """

    def result(reason: str) -> dict[str, Any]:
        return {
            "schema_version": "wolf15.channel-b-replay.v1",
            "input_replay_consistent": reason == "CONSISTENT_REPLAY",
            "reason": reason,
            "independent_reader_attestation": "NOT_VERIFIED",
            "execution_authority": False,
            "production_ready": False,
        }

    try:
        if (
            any(
                not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
                for t in (window_from, window_to, as_of)
            )
            or not isinstance(maximum_age, timedelta)
            or maximum_age <= timedelta(0)
            or not window_from < window_to <= as_of
        ):
            return result("INVALID_VERIFIER_SCOPE")
        if not verify_report_integrity(report, expected_receipt_digest=expected_receipt_digest):
            return result("REPORT_INTEGRITY_MISMATCH")
        receipt = report["integrity"]
        if not expected_sources or receipt["orchestrator_sources"] != expected_sources:
            return result("SOURCE_BINDING_MISMATCH")
        if receipt["database_snapshot_digest"] != evidence_digest(database) or receipt[
            "broker_snapshot_digest"
        ] != evidence_digest(broker):
            return result("INPUT_DIGEST_MISMATCH")
        if report.get("window") != {"from_utc": reconcile._iso(window_from), "to_utc": reconcile._iso(window_to)}:
            return result("WINDOW_MISMATCH")
        interval = broker.get("collection_interval", {})
        started = reconcile._evidence_time(interval.get("started_at_utc"))
        finished = reconcile._evidence_time(interval.get("finished_at_utc"))
        if started is None or finished is None or not window_to <= started <= finished <= as_of:
            return result("COLLECTION_CLOCK_MISMATCH")
        # Age is measured from collection start, so a long collection cannot
        # make an old observation fresh merely by finishing recently.
        if as_of - started > maximum_age:
            return result("REPORT_TOO_OLD")
        identity_state, _, identity = reconcile._direct_identity(broker)
        if (
            identity_state != "MEASURED"
            or identity is None
            or not account_binding.identifiers_match(identity["identifier"], expected_account_identifier)
        ):
            return result("ACCOUNT_SCOPE_MISMATCH")
        replayed = reconcile.reconcile_snapshots(
            database=database, broker=broker, window_from=window_from, window_to=window_to
        )
        body = {key: value for key, value in report.items() if key != "integrity"}
        if evidence_digest(replayed) != evidence_digest(body):
            return result("EVALUATION_REPLAY_MISMATCH")
        if replayed["B-B16"] != "EXECUTED_PASS":
            return result("RECONCILIATION_GATE_NOT_PASS")
        return result("CONSISTENT_REPLAY")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return result("MALFORMED_REPLAY_EVIDENCE")
