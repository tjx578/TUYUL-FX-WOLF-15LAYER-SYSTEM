from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from execution.broker_reconciliation_evidence import (
    ISSUER_KEY_ENV,
    ReconciliationEvidenceError,
    attest_collected_reconciliation,
    verify_attestation,
)
from tests.reconciliation_fixtures import (
    collected_fixture,
    configure_test_keys,
    fixture_attestation,
    fixture_identity,
)
from tests.test_mt5_engineering_demo_canary import SECRET, _executor, _request, _snapshot


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    configure_test_keys(monkeypatch)


def test_signed_evidence_with_false_executor_observation_is_valid():
    snapshot = _snapshot()
    assert snapshot.broker_ledger_reconciled is False
    identity = fixture_identity(snapshot)
    proof = verify_attestation(fixture_attestation(identity), identity=identity, snapshot=snapshot, now=datetime.now(UTC))
    assert proof.status == "MATCHED_FLAT_DEMO"


@pytest.mark.parametrize("fault", ["report_hash", "signature", "unknown_issuer", "wrong_key_id", "future", "old_snapshot"])
def test_authentication_scope_and_freshness_fail_closed(fault):
    snapshot = _snapshot()
    identity = fixture_identity(snapshot)
    evidence = fixture_attestation(identity)
    if fault == "report_hash":
        evidence["report_sha256"] = "0" * 64
    elif fault == "signature":
        evidence["signature"] = "0" * 64
    elif fault == "unknown_issuer":
        evidence["issuer"] = "untrusted"
    elif fault == "wrong_key_id":
        evidence["issuer_key_id"] = "unknown"
    elif fault == "future":
        evidence["issued_at_utc"] = (datetime.now(UTC)+timedelta(hours=1)).isoformat()
    else:
        snapshot = snapshot.model_copy(update={"captured_at_utc": datetime.now(UTC)-timedelta(minutes=1)})
    with pytest.raises(ReconciliationEvidenceError):
        verify_attestation(evidence, identity=identity, snapshot=snapshot, now=datetime.now(UTC))


@pytest.mark.parametrize("fault", ["missing_projection", "terminal_identity", "unmeasured", "truncated", "real_account", "open_position", "wrong_server", "stale_collection"])
def test_collector_refuses_nonqualifying_inputs(fault):
    identity = fixture_identity(_snapshot())
    database, broker, start, end = collected_fixture(identity)
    if fault == "missing_projection":
        database.pop("backend_identity")
    elif fault == "terminal_identity":
        database["backend_identity"] = [{**identity, "account_binding_source": "TERMINAL_REPORT"}]
    elif fault == "unmeasured":
        broker["snapshots"]["mt5_orders_get"]["measurement_state"] = "NOT_MEASURED"
    elif fault == "truncated":
        database["truncated"] = True
    elif fault == "real_account":
        broker["snapshots"]["mt5_account_get"]["records"][0]["trade_mode"] = 2
    elif fault == "open_position":
        broker["snapshots"]["mt5_positions_get"]["records"] = [{"ticket": 123}]
    elif fault == "wrong_server":
        database["backend_identity"] = [{**identity, "broker_server": "other"}]
    else:
        database["observed_at_utc"] = (datetime.now(UTC)-timedelta(seconds=31)).isoformat()
    with pytest.raises(ReconciliationEvidenceError):
        attest_collected_reconciliation(database=database, broker=broker, window_from=start, window_to=end)


def test_identity_key_cannot_replace_issuer_key(monkeypatch):
    import os

    from ops.mt5_mcp.account_binding import KEY_ENV

    monkeypatch.setenv(ISSUER_KEY_ENV, os.environ[KEY_ENV])
    with pytest.raises(ReconciliationEvidenceError, match="KEY_REUSE"):
        fixture_attestation(fixture_identity(_snapshot()))


@pytest.mark.parametrize("flag", [True, False])
def test_direct_builder_cannot_use_heartbeat_boolean_as_proof(flag):
    from execution.mt5_engineering_demo_canary import EngineeringDemoCanaryError, build_engineering_demo_canary_command

    with pytest.raises(EngineeringDemoCanaryError, match="RECONCILIATION_EVIDENCE_MISSING"):
        build_engineering_demo_canary_command(
            _request(), executor=_executor(), snapshot=_snapshot(broker_ledger_reconciled=flag),
            signing_secret=SECRET, signing_key_id="d0-test-key",
        )


def test_changing_report_and_recomputing_plain_hash_does_not_forge_mac():
    from execution.broker_reconciliation_evidence import digest

    snapshot = _snapshot()
    identity = fixture_identity(snapshot)
    evidence = fixture_attestation(identity)
    forged = copy.deepcopy(evidence)
    forged["report_sha256"] = digest({"B-B16": "EXECUTED_PASS"})
    assert digest(forged) != digest(evidence)
    with pytest.raises(ReconciliationEvidenceError, match="AUTHENTICATION_FAILED"):
        verify_attestation(forged, identity=identity, snapshot=snapshot, now=datetime.now(UTC))
