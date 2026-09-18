"""Exact identity-bound snapshot reconciliation (S, not "latest").

identity binds snapshot S; newer heartbeat snapshots S+1, S+2 must not invalidate S while S is
still canonically fresh. Collector and importer both bind to S exactly.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from execution.broker_reconciliation_evidence import (
    ReconciliationEvidenceError,
    attest_collected_reconciliation,
    snapshot_digest,
    verify_attestation,
)
from execution.broker_reconciliation_repository import store_evidence
from tests.reconciliation_fixtures import collected_fixture, configure_test_keys, fixture_identity
from tests.test_mt5_engineering_demo_canary import _executor, _snapshot


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    configure_test_keys(monkeypatch)


def _snapshots(age_seconds: float = 12.0):
    now = datetime.now(UTC)
    bound = _snapshot(snapshot_id="snapshot-S", captured_at_utc=now - timedelta(seconds=age_seconds))
    newer = _snapshot(snapshot_id="snapshot-S1", captured_at_utc=now - timedelta(seconds=2))
    newest = _snapshot(snapshot_id="snapshot-S2", captured_at_utc=now)
    return bound, newer, newest


def _collect(identity: dict[str, Any], *, latest: str) -> dict[str, Any]:
    database, broker, start, end = collected_fixture(identity)
    database["executor_freshness"][0]["latest_snapshot_id"] = latest
    return attest_collected_reconciliation(database=database, broker=broker, window_from=start, window_to=end)


class FakeConnection:
    """Answers only the exact queries store_evidence/current_identity issue."""

    def __init__(self, *, executor, snapshots, binding):
        self.executor = executor
        self.snapshots = {snapshot.snapshot_id: snapshot.model_dump(mode="json") for snapshot in snapshots}
        self.binding = binding
        self.inserted: list[tuple[Any, ...]] = []
        self.executed: list[str] = []

    async def fetchrow(self, sql: str, *args: Any):
        if "FROM executor_instances" in sql:
            return self.executor if str(args[0]) == str(self.executor["executor_id"]) else None
        if "FROM executor_account_snapshots WHERE snapshot_id=$1 AND executor_id=$2" in sql:
            snapshot_id, executor_id = args
        elif "FROM executor_account_snapshots WHERE executor_id=$1::uuid AND snapshot_id=$2" in sql:
            executor_id, snapshot_id = args
        elif "FROM executor_reconciliation_bindings" in sql:
            return self.binding
        else:
            raise AssertionError(f"unexpected query: {sql}")
        payload = self.snapshots.get(snapshot_id)
        if payload is None or str(payload["executor_id"]) != str(executor_id):
            return None
        return {"payload": json.dumps(payload)}

    async def fetchval(self, sql: str, *args: Any):
        assert sql.lstrip().startswith("INSERT INTO broker_reconciliation_evidence")
        self.inserted.append(args)
        return args[0]

    async def execute(self, sql: str, *args: Any):
        self.executed.append(sql)


def _binding_row(identity: dict[str, Any], executor: dict[str, Any]) -> dict[str, Any]:
    return {
        "executor_id": identity["executor_id"],
        "binding_version": identity["binding_version"],
        "account_id": executor["account_id"],
        "login_hash": executor["login_hash"],
        "broker_server": identity["broker_server"],
        "account_binding_identifier": identity["account_binding_identifier"],
        "snapshot_id": identity["snapshot_id"],
        "snapshot_sha256": identity["snapshot_sha256"],
    }


def _backend(bound, *snapshots, executor=None):
    executor = executor or {**_executor(), "revoked_at": None}
    identity = fixture_identity(bound)
    connection = FakeConnection(
        executor=executor, snapshots=[bound, *snapshots], binding=_binding_row(identity, executor)
    )
    return identity, connection


# --- collector ---------------------------------------------------------------------------


@pytest.mark.parametrize("latest", ["snapshot-S", "snapshot-S1", "snapshot-S2"])
def test_collector_binds_identity_snapshot_even_when_newer_snapshots_exist(latest):
    bound, _, _ = _snapshots()
    identity = fixture_identity(bound)
    evidence = _collect(identity, latest=latest)
    assert evidence["snapshot_id"] == "snapshot-S"
    assert evidence["snapshot_sha256"] == snapshot_digest(bound)


@pytest.mark.parametrize(
    "fault", ["no_freshness_row", "other_executor", "duplicate_row", "no_latest", "no_snapshot_id", "bad_digest"]
)
def test_collector_still_fails_closed_on_missing_or_malformed_binding(fault):
    bound, _, _ = _snapshots()
    identity = fixture_identity(bound)
    database, broker, start, end = collected_fixture(identity)
    row = database["executor_freshness"][0]
    if fault == "no_freshness_row":
        database["executor_freshness"] = []
    elif fault == "other_executor":
        row["executor_id"] = "00000000-0000-0000-0000-000000000000"
    elif fault == "duplicate_row":
        database["executor_freshness"] = [row, dict(row)]
    elif fault == "no_latest":
        row["latest_snapshot_id"] = None
    elif fault == "no_snapshot_id":
        database["backend_identity"] = [{**identity, "snapshot_id": ""}]
    else:
        database["backend_identity"] = [{**identity, "snapshot_sha256": "Z" * 64}]
    # Freshness-row faults are already rejected upstream by reconcile_snapshots (B-B16);
    # either rejection is fail-closed. Binding-shape faults must hit the exact-S guard.
    expected = (
        "RECONCILIATION_"
        if fault in {"no_freshness_row", "other_executor", "no_latest"}
        else ("RECONCILIATION_SNAPSHOT_BINDING_MISMATCH")
    )
    with pytest.raises(ReconciliationEvidenceError, match=expected):
        attest_collected_reconciliation(database=database, broker=broker, window_from=start, window_to=end)


# --- importer (store_evidence) -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", ["snapshot-S", "snapshot-S1", "snapshot-S2"])
async def test_heartbeat_during_collection_no_longer_breaks_import(latest):
    """Regression: S+1/S+2 arriving while the collector runs must not reject evidence for S."""
    bound, newer, newest = _snapshots(age_seconds=12)
    identity, connection = _backend(bound, newer, newest)
    evidence = _collect(identity, latest=latest)
    await store_evidence(connection, evidence)
    assert connection.inserted[0][3] == "snapshot-S"
    assert any("SET status='REVOKED'" in sql for sql in connection.executed)


@pytest.mark.asyncio
async def test_import_rejects_evidence_for_newer_snapshot_than_identity():
    bound, newer, _ = _snapshots()
    identity, connection = _backend(bound, newer)
    evidence = _collect(fixture_identity(newer), latest="snapshot-S1")
    with pytest.raises(ReconciliationEvidenceError, match="RECONCILIATION_BINDING_MISMATCH"):
        await store_evidence(connection, evidence)
    assert connection.inserted == []


@pytest.mark.asyncio
async def test_import_rejects_when_identity_snapshot_is_missing():
    bound, newer, _ = _snapshots()
    identity, connection = _backend(bound, newer)
    evidence = _collect(identity, latest="snapshot-S1")
    del connection.snapshots["snapshot-S"]
    with pytest.raises(ReconciliationEvidenceError, match="RECONCILIATION_SNAPSHOT_MISSING"):
        await store_evidence(connection, evidence)


@pytest.mark.asyncio
async def test_import_rejects_identity_snapshot_older_than_canonical_age():
    bound, newer, _ = _snapshots(age_seconds=31)
    identity, connection = _backend(bound, newer)
    evidence = _collect(identity, latest="snapshot-S1")
    with pytest.raises(ReconciliationEvidenceError, match="RECONCILIATION_EVIDENCE_STALE"):
        await store_evidence(connection, evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["executor", "server", "account", "digest", "snapshot_id", "mac", "snapshot_changed"])
async def test_import_keeps_every_other_guard(fault):
    bound, newer, _ = _snapshots()
    identity, connection = _backend(bound, newer)
    evidence = _collect(identity, latest="snapshot-S1")
    if fault == "executor":
        connection.executor = {**connection.executor, "execution_mode": "SHADOW"}
    elif fault == "server":
        connection.binding = {**connection.binding, "broker_server": "Other-Server"}
    elif fault == "account":
        connection.binding = {**connection.binding, "account_id": "other-account"}
    elif fault == "digest":
        connection.binding = {**connection.binding, "snapshot_sha256": "0" * 64}
    elif fault == "snapshot_id":
        connection.binding = {**connection.binding, "snapshot_id": "snapshot-S1"}
    elif fault == "mac":
        evidence = copy.deepcopy(evidence)
        evidence["signature"] = "0" * 64
    else:
        connection.snapshots["snapshot-S"]["free_margin"] -= 1  # S mutated after identity bound it
    with pytest.raises(ReconciliationEvidenceError):
        await store_evidence(connection, evidence)
    assert connection.inserted == []


@pytest.mark.parametrize("field", ["executor_id", "account_binding_identifier", "broker_server", "snapshot_sha256"])
def test_verify_rejects_identity_field_drift(field):
    bound, _, _ = _snapshots()
    identity = fixture_identity(bound)
    evidence = _collect(identity, latest="snapshot-S1")
    drifted = dict(identity)
    drifted[field] = {
        "executor_id": "00000000-0000-0000-0000-000000000000",
        "account_binding_identifier": identity["account_binding_identifier"][:-4] + "AAAA",
        "broker_server": "Other-Server",
        "snapshot_sha256": "0" * 64,
    }[field]
    with pytest.raises(ReconciliationEvidenceError):
        verify_attestation(evidence, identity=drifted, snapshot=bound, now=datetime.now(UTC))
