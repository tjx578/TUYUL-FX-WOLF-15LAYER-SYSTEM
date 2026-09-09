"""Channel B integrity receipts; hashes do not authenticate a broker reader."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

SCHEMA = "wolf15.channel-b-integrity.v1"


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("NAIVE_EVIDENCE_TIMESTAMP")
        return {"datetime": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NONFINITE_EVIDENCE_DECIMAL")
        return {"decimal": str(value)}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    raise TypeError("UNSUPPORTED_EVIDENCE_VALUE")


def evidence_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=_encode
    )
    return "sha256:" + hashlib.sha256(encoded.encode("ascii")).hexdigest()


def orchestrator_sources() -> dict[str, str]:
    """Local orchestration files only, not the configured external MCP server."""
    directory = Path(__file__).resolve().parent
    return {
        name: "sha256:" + hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("reconcile.py", "report_integrity.py", "account_binding.py")
    }


def seal_report(
    report: dict[str, Any],
    *,
    database: dict[str, Any],
    broker: dict[str, Any],
    sources_before: dict[str, str],
    sources_after: dict[str, str],
) -> dict[str, Any]:
    if not sources_before or sources_before != sources_after:
        raise ValueError("RECONCILIATION_SOURCE_CHANGED_OR_MISSING")
    if "integrity" in report:
        raise ValueError("REPORT_ALREADY_SEALED")
    # Detach nested report objects so later caller mutation cannot silently
    # alter the returned report through shared references.
    detached = json.loads(json.dumps(report, default=_encode, allow_nan=False))
    integrity = {
        "schema_version": SCHEMA,
        "evidence_class": "INTEGRITY_ONLY_NOT_ATTESTED",
        "database_snapshot_digest": evidence_digest(database),
        "broker_snapshot_digest": evidence_digest(broker),
        "orchestrator_sources": dict(sources_before),
        "collector_identity": "UNVERIFIED",
        "report_payload_digest": evidence_digest(detached),
    }
    integrity["receipt_digest"] = evidence_digest(integrity)
    return {**detached, "integrity": integrity}


def verify_report_integrity(report: dict[str, Any], *, expected_receipt_digest: str) -> bool:
    """Compare against an externally retained digest; grants no execution authority."""
    try:
        integrity = report["integrity"]
        if integrity["schema_version"] != SCHEMA or integrity["evidence_class"] != "INTEGRITY_ONLY_NOT_ATTESTED":
            return False
        if not isinstance(expected_receipt_digest, str) or len(expected_receipt_digest) != 71:
            return False
        body = {key: value for key, value in report.items() if key != "integrity"}
        receipt = {key: value for key, value in integrity.items() if key != "receipt_digest"}
        return (
            hmac.compare_digest(evidence_digest(body), integrity["report_payload_digest"])
            and hmac.compare_digest(evidence_digest(receipt), integrity["receipt_digest"])
            and hmac.compare_digest(integrity["receipt_digest"], expected_receipt_digest)
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
