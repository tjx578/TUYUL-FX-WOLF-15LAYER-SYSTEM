"""Backend identity producer and locked evidence consumption for D0 gates."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts.mt5_execution_protocol import AccountSnapshotV1
from execution.broker_reconciliation_evidence import (
    ReconciliationAttestation,
    ReconciliationEvidenceError,
    canonical,
    digest,
    snapshot_digest,
    verify_attestation,
)
from ops.mt5_mcp import account_binding


def _object(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


async def produce_backend_identity(connection: Any, executor_id: UUID | str) -> dict[str, Any]:
    """Privileged backend path: no caller-supplied login, server, or terminal identity.

    Opaque account IDs fail canonical_login; provisioning must establish the real
    binding independently. A terminal report can never repair this mismatch.
    Caller owns a transaction. Lock order is executor, snapshot, binding.
    """
    executor = await connection.fetchrow(
        "SELECT * FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE", str(executor_id)
    )
    if not executor or executor["revoked_at"] is not None or executor["execution_mode"] != "DEMO":
        raise ReconciliationEvidenceError("RECONCILIATION_EXECUTOR_UNAVAILABLE")
    row = await connection.fetchrow(
        """SELECT payload FROM executor_account_snapshots WHERE executor_id=$1::uuid
           AND account_id=$2 ORDER BY captured_at DESC LIMIT 1 FOR SHARE""",
        str(executor_id),
        executor["account_id"],
    )
    if not row:
        raise ReconciliationEvidenceError("RECONCILIATION_SNAPSHOT_MISSING")
    raw_snapshot = _object(row["payload"])
    snapshot = AccountSnapshotV1.model_validate(raw_snapshot)
    if not 0 <= (datetime.now(UTC) - snapshot.captured_at_utc).total_seconds() <= 30:
        raise ReconciliationEvidenceError("RECONCILIATION_SNAPSHOT_STALE")
    identity = account_binding.identifier(
        secret_key=account_binding.decode_secret_key(os.getenv(account_binding.KEY_ENV, "")),
        key_id=os.getenv(account_binding.KEY_ID_ENV, ""),
        login=executor["account_id"],
        server=executor["broker_server"],
    )
    await connection.execute(
        """INSERT INTO executor_reconciliation_bindings AS b
           (executor_id, binding_version, account_id, login_hash, broker_server,
            account_binding_identifier, snapshot_id, snapshot_sha256, snapshot_payload)
           VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9::jsonb)
           ON CONFLICT (executor_id) DO UPDATE SET
             binding_version=EXCLUDED.binding_version, account_id=EXCLUDED.account_id,
             login_hash=EXCLUDED.login_hash, broker_server=EXCLUDED.broker_server,
             account_binding_identifier=EXCLUDED.account_binding_identifier,
             snapshot_id=EXCLUDED.snapshot_id, snapshot_sha256=EXCLUDED.snapshot_sha256,
             snapshot_payload=EXCLUDED.snapshot_payload, created_at=clock_timestamp()
           WHERE (b.account_id,b.login_hash,b.broker_server,b.account_binding_identifier,b.snapshot_sha256)
             IS DISTINCT FROM (EXCLUDED.account_id,EXCLUDED.login_hash,EXCLUDED.broker_server,
                               EXCLUDED.account_binding_identifier,EXCLUDED.snapshot_sha256)""",
        str(executor_id),
        str(uuid4()),
        executor["account_id"],
        executor["login_hash"],
        executor["broker_server"],
        identity,
        snapshot.snapshot_id,
        snapshot_digest(snapshot),
        json.dumps(raw_snapshot),
    )
    return dict(
        await connection.fetchrow(
            "SELECT * FROM wolf15_audit.backend_account_identity_v1 WHERE executor_id=$1::uuid", str(executor_id)
        )
    )


async def current_identity(connection: Any, executor_id: UUID | str, snapshot: AccountSnapshotV1) -> dict[str, Any]:
    row = await connection.fetchrow(
        """SELECT b.*, e.execution_mode, e.revoked_at FROM executor_reconciliation_bindings b
           JOIN executor_instances e ON e.executor_id=b.executor_id
           WHERE b.executor_id=$1::uuid AND b.account_id=e.account_id AND b.login_hash=e.login_hash
             AND b.broker_server=e.broker_server FOR SHARE OF b, e""",
        str(executor_id),
    )
    if not row or row["execution_mode"] != "DEMO" or row["revoked_at"] is not None:
        raise ReconciliationEvidenceError("RECONCILIATION_BACKEND_BINDING_MISSING")
    if row["account_id"] != snapshot.account_id or row["snapshot_sha256"] != snapshot_digest(snapshot):
        raise ReconciliationEvidenceError("RECONCILIATION_BINDING_MISMATCH")
    return {**dict(row), "account_binding_source": account_binding.DATABASE_SOURCE}


async def load_evidence(
    connection: Any,
    *,
    executor_id: UUID | str,
    snapshot: AccountSnapshotV1,
    evidence_id: UUID | None = None,
    expected_digest: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = await current_identity(connection, executor_id, snapshot)
    row = await connection.fetchrow(
        """SELECT * FROM broker_reconciliation_evidence
           WHERE executor_id=$1::uuid AND snapshot_id=$2
             AND ($3::uuid IS NULL OR evidence_id=$3::uuid)
           ORDER BY created_at DESC, evidence_id DESC LIMIT 1 FOR SHARE""",
        str(executor_id),
        snapshot.snapshot_id,
        str(evidence_id) if evidence_id else None,
    )
    if not row or row["status"] != "ACTIVE":
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_MISSING_OR_REVOKED")
    evidence = _object(row["payload"])
    actual_digest = digest(evidence)
    if row["payload_sha256"] != actual_digest or (expected_digest is not None and expected_digest != actual_digest):
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_CHANGED")
    proof = verify_attestation(evidence, identity=identity, snapshot=snapshot, now=datetime.now(UTC))
    if str(proof.evidence_id) != str(row["evidence_id"]) or str(proof.binding_version) != str(row["binding_version"]):
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_CHANGED")
    return identity, evidence


async def store_evidence(connection: Any, evidence: dict[str, Any]) -> str:
    """Backend ingestion authenticates; auditor never receives write permissions."""
    proof = ReconciliationAttestation.model_validate(evidence)
    # Same lock ordering as producer and command gates.
    await connection.fetchrow(
        "SELECT executor_id FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE",
        str(proof.executor_id),
    )
    row = await connection.fetchrow(
        "SELECT payload FROM executor_account_snapshots WHERE snapshot_id=$1 AND executor_id=$2::uuid FOR SHARE",
        proof.snapshot_id,
        str(proof.executor_id),
    )
    if not row:
        raise ReconciliationEvidenceError("RECONCILIATION_SNAPSHOT_MISSING")
    snapshot = AccountSnapshotV1.model_validate(_object(row["payload"]))
    identity = await current_identity(connection, proof.executor_id, snapshot)
    verify_attestation(evidence, identity=identity, snapshot=snapshot, now=datetime.now(UTC))
    receipt_digest = digest(evidence)
    inserted = await connection.fetchval(
        """INSERT INTO broker_reconciliation_evidence
           (evidence_id,executor_id,binding_version,snapshot_id,payload,payload_sha256,status)
           VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5::jsonb,$6,'ACTIVE')
           ON CONFLICT (evidence_id) DO NOTHING RETURNING evidence_id""",
        str(proof.evidence_id),
        str(proof.executor_id),
        str(proof.binding_version),
        proof.snapshot_id,
        canonical(evidence).decode(),
        receipt_digest,
    )
    if inserted is None:
        raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_REPLAY")
    # A newer valid collection supersedes the earlier receipt. Revocation and
    # import commit together; enqueue/arm hold SHARE locks on the pinned row.
    await connection.execute(
        "UPDATE broker_reconciliation_evidence SET status='REVOKED' WHERE executor_id=$1::uuid AND evidence_id<>$2::uuid AND status='ACTIVE'",
        str(proof.executor_id),
        str(proof.evidence_id),
    )
    return receipt_digest
