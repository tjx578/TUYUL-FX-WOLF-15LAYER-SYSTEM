"""Authenticated, short-lived Channel B evidence; never trade authority by itself.

The issuer MAC key is separate from account identity and execution signing keys.
Only the controlled reconciliation collector and backend verifier hold it. This
authenticates that trust domain, not an arbitrary local JSON file or MT5 process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.mt5_execution_protocol import AccountSnapshotV1
from ops.mt5_mcp import account_binding

ISSUER = "wolf15-channel-b-collector-v1"
ISSUER_KEY_ENV = "WOLF15_RECONCILIATION_ISSUER_KEY_B64URL"
ISSUER_KEY_ID_ENV = "WOLF15_RECONCILIATION_ISSUER_KEY_ID"
MAX_AGE_SECONDS = 30
DOMAIN = b"WOLF15\x00D0_RECONCILIATION_ATTESTATION\x00V1\x00"


class ReconciliationEvidenceError(ValueError):
    """A non-secret, fail-closed evidence error."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def snapshot_digest(snapshot: AccountSnapshotV1) -> str:
    return digest(snapshot.model_dump(mode="json"))


def issuer_key() -> tuple[str, bytes]:
    try:
        key_id = account_binding.validate_key_id(os.getenv(ISSUER_KEY_ID_ENV, ""))
        key = account_binding.decode_secret_key(os.getenv(ISSUER_KEY_ENV, ""))
        binding_key = os.getenv(account_binding.KEY_ENV, "")
        if binding_key and hmac.compare_digest(key, account_binding.decode_secret_key(binding_key)):
            raise ReconciliationEvidenceError("RECONCILIATION_KEY_REUSE")
        for name in ("EXECUTOR_COMMAND_SIGNING_SECRET", "EXECUTOR_BRIDGE_AUTH_SECRET"):
            if os.getenv(name) and hmac.compare_digest(key, os.environ[name].encode()):
                raise ReconciliationEvidenceError("RECONCILIATION_KEY_REUSE")
        return key_id, key
    except account_binding.AccountBindingError as exc:
        raise ReconciliationEvidenceError("RECONCILIATION_ISSUER_KEY_UNAVAILABLE") from exc


class ReconciliationAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["wolf15.d0-reconciliation-attestation.v1"] = "wolf15.d0-reconciliation-attestation.v1"
    issuer: Literal["wolf15-channel-b-collector-v1"] = ISSUER
    issuer_key_id: str
    evidence_id: UUID
    binding_version: UUID
    executor_id: UUID
    account_binding_identifier: str
    broker_server: str
    snapshot_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["MATCHED_FLAT_DEMO"]
    observed_at_utc: datetime
    issued_at_utc: datetime
    expires_at_utc: datetime
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at_utc", "issued_at_utc", "expires_at_utc")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence timestamp must be timezone aware")
        return value.astimezone(UTC)


def verify_attestation(
    evidence: dict[str, Any], *, identity: dict[str, Any], snapshot: AccountSnapshotV1, now: datetime
) -> ReconciliationAttestation:
    try:
        proof = ReconciliationAttestation.model_validate(evidence)
        key_id, key = issuer_key()
        signed = proof.model_dump(mode="json", exclude={"signature"})
        mac = hmac.new(key, DOMAIN + canonical(signed), hashlib.sha256).hexdigest()
        if proof.issuer_key_id != key_id or not hmac.compare_digest(mac, proof.signature):
            raise ReconciliationEvidenceError("RECONCILIATION_ISSUER_AUTHENTICATION_FAILED")
        if not (
            proof.observed_at_utc <= proof.issued_at_utc <= now < proof.expires_at_utc
            and 0 <= (now - snapshot.captured_at_utc).total_seconds() <= MAX_AGE_SECONDS
            and 0 < (proof.expires_at_utc - proof.observed_at_utc).total_seconds() <= MAX_AGE_SECONDS
        ):
            raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_STALE")
        if (
            str(proof.binding_version) != str(identity["binding_version"])
            or str(proof.executor_id) != str(identity["executor_id"])
            or proof.executor_id != snapshot.executor_id
            or proof.broker_server != identity["broker_server"]
            or not account_binding.identifiers_match(
                proof.account_binding_identifier, identity["account_binding_identifier"]
            )
            or proof.snapshot_id != identity["snapshot_id"]
            or proof.snapshot_id != snapshot.snapshot_id
            or proof.snapshot_sha256 != identity["snapshot_sha256"]
            or proof.snapshot_sha256 != snapshot_digest(snapshot)
            or identity["account_binding_source"] != account_binding.DATABASE_SOURCE
        ):
            raise ReconciliationEvidenceError("RECONCILIATION_BINDING_MISMATCH")
        return proof
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ReconciliationEvidenceError):
            raise
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_INVALID") from exc


def attest_collected_reconciliation(
    *, database: dict[str, Any], broker: dict[str, Any], window_from: datetime, window_to: datetime
) -> dict[str, Any]:
    """Called ONLY by the trusted collector on its own fresh reads, never by an import endpoint.

    A hash-sealed legacy report is deliberately not an input to this function.
    Identity comes from the backend audit projection, independently of MT5.
    """
    from ops.mt5_mcp.reconcile import reconcile_snapshots

    report = reconcile_snapshots(database=database, broker=broker, window_from=window_from, window_to=window_to)
    if report["B-B16"] != "EXECUTED_PASS" or report["BROKER_RECONCILIATION"] != "MATCHED":
        raise ReconciliationEvidenceError("RECONCILIATION_NOT_MATCHED")
    identities = database.get("backend_identity", [])
    if len(identities) != 1:
        raise ReconciliationEvidenceError("RECONCILIATION_BACKEND_IDENTITY_AMBIGUOUS")
    identity = identities[0]
    if identity.get("account_binding_source") != account_binding.DATABASE_SOURCE:
        raise ReconciliationEvidenceError("RECONCILIATION_BACKEND_IDENTITY_UNTRUSTED")
    freshness = database.get("executor_freshness", [])
    if not any(
        str(row.get("executor_id")) == str(identity["executor_id"])
        and row.get("latest_snapshot_id") == identity["snapshot_id"]
        for row in freshness
    ):
        raise ReconciliationEvidenceError("RECONCILIATION_SNAPSHOT_BINDING_MISMATCH")
    session = database.get("audit_session", {})
    if (
        session.get("current_role") != "wolf15_auditor"
        or session.get("transaction_read_only") is not True
        or session.get("transaction_isolation") != "repeatable read"
    ):
        raise ReconciliationEvidenceError("RECONCILIATION_AUDITOR_SESSION_INVALID")
    snapshots = broker["snapshots"]
    for payload in snapshots.values():
        if (
            payload.get("error_code") is not None
            or not account_binding.identifiers_match(
                payload["account_binding"]["identifier"], identity["account_binding_identifier"]
            )
            or payload["account_binding"]["server"] != identity["broker_server"]
        ):
            raise ReconciliationEvidenceError("RECONCILIATION_BINDING_MISMATCH")
    account = snapshots["mt5_account_get"]["records"]
    if (
        len(account) != 1
        or type(account[0].get("trade_mode")) is not int
        or account[0]["trade_mode"] != 0
        or snapshots["mt5_positions_get"]["records"]
        or snapshots["mt5_orders_get"]["records"]
    ):
        raise ReconciliationEvidenceError("RECONCILIATION_NOT_FLAT_DEMO")
    now = datetime.now(UTC)
    observed = datetime.fromisoformat(broker["collection_interval"]["started_at_utc"])
    database_observed = datetime.fromisoformat(database["observed_at_utc"])
    finished = datetime.fromisoformat(broker["collection_interval"]["finished_at_utc"])
    if finished > now or database_observed > now:
        raise ReconciliationEvidenceError("RECONCILIATION_COLLECTION_CLOCK_INVALID")
    observed = min(observed, database_observed)
    if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() < MAX_AGE_SECONDS:
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_STALE")
    key_id, key = issuer_key()
    proof = ReconciliationAttestation(
        issuer_key_id=key_id,
        evidence_id=uuid4(),
        binding_version=identity["binding_version"],
        executor_id=identity["executor_id"],
        account_binding_identifier=identity["account_binding_identifier"],
        broker_server=identity["broker_server"],
        snapshot_id=identity["snapshot_id"],
        snapshot_sha256=identity["snapshot_sha256"],
        report_sha256=digest(report),
        status="MATCHED_FLAT_DEMO",
        observed_at_utc=observed,
        issued_at_utc=now,
        expires_at_utc=observed + timedelta(seconds=MAX_AGE_SECONDS),
        signature="0" * 64,
    )
    payload = proof.model_dump(mode="json", exclude={"signature"})
    payload["signature"] = hmac.new(key, DOMAIN + canonical(payload), hashlib.sha256).hexdigest()
    return payload
