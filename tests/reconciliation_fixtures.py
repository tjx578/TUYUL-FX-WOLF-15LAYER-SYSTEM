"""Synthetic collector inputs and keys ONLY for disposable/local tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from execution.broker_reconciliation_evidence import (
    ISSUER_KEY_ENV,
    ISSUER_KEY_ID_ENV,
    attest_collected_reconciliation,
    snapshot_digest,
)
from ops.mt5_mcp import account_binding

IDENTITY_TEST_KEY = b"test-identity-key-" * 2
ISSUER_TEST_KEY = b"test-issuer-key-" * 3


def configure_test_keys(monkeypatch: Any) -> None:
    monkeypatch.setenv(account_binding.KEY_ENV, base64.urlsafe_b64encode(IDENTITY_TEST_KEY).rstrip(b"=").decode())
    monkeypatch.setenv(account_binding.KEY_ID_ENV, "disposable-identity")
    monkeypatch.setenv(ISSUER_KEY_ENV, base64.urlsafe_b64encode(ISSUER_TEST_KEY).rstrip(b"=").decode())
    monkeypatch.setenv(ISSUER_KEY_ID_ENV, "disposable-issuer")


def fixture_identity(snapshot: Any, *, server: str = "Broker-Demo", login: str = "12345678") -> dict[str, Any]:
    return {
        "executor_id": str(snapshot.executor_id),
        "binding_version": str(uuid4()),
        "broker_server": server,
        "account_binding_source": account_binding.DATABASE_SOURCE,
        "account_binding_identifier": account_binding.identifier(
            secret_key=IDENTITY_TEST_KEY, key_id="disposable-identity", login=login, server=server
        ),
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256": snapshot_digest(snapshot),
    }


def collected_fixture(identity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], datetime, datetime]:
    now = datetime.now(UTC) - timedelta(milliseconds=10)
    start = now - timedelta(days=7)
    window = {"from_utc": start.isoformat(), "to_utc": now.isoformat()}
    snapshots = {}
    for tool in (
        "mt5_account_get",
        "mt5_positions_get",
        "mt5_orders_get",
        "mt5_history_deals_get",
        "mt5_history_orders_get",
    ):
        records = [{"trade_mode": 0}] if tool == "mt5_account_get" else []
        snapshots[tool] = {
            "measurement_state": "MEASURED" if records else "MEASURED_EMPTY",
            "records": records,
            "record_count": len(records),
            "source_record_count": len(records),
            "truncated": False,
            "error_code": None,
            "observed_at_utc": now.isoformat(),
            "window": window,
            "account_binding": {
                "scheme": account_binding.SCHEME,
                "version": account_binding.VERSION,
                "algorithm": account_binding.ALGORITHM,
                "key_id": "disposable-identity",
                "identifier": identity["account_binding_identifier"],
                "server": identity["broker_server"],
            },
            "terminal": {"path_sha256": "a" * 64, "version": [500, 5000]},
        }
    broker = {
        "tool_surface_exact": True,
        "window": window,
        "snapshots": snapshots,
        "collection_interval": {"started_at_utc": now.isoformat(), "finished_at_utc": now.isoformat()},
    }
    database = {
        "measured": True,
        "truncated": False,
        "observed_at_utc": now.isoformat(),
        "audit_session": {
            "current_role": "wolf15_auditor",
            "transaction_read_only": True,
            "transaction_isolation": "repeatable read",
        },
        "mutation_evidence": {"xid_unassigned": True, "changed_tuples": 0},
        "executor_identity": [{"executor_id": identity["executor_id"], "revoked_at": None}],
        "executor_freshness": [
            {
                "executor_id": identity["executor_id"],
                "status": "ONLINE",
                "heartbeat_age_seconds": 0,
                "snapshot_age_seconds": 0,
                "latest_snapshot_id": identity["snapshot_id"],
            }
        ],
        "account_binding": [
            {
                **identity,
                "latest_snapshot_account_matches": True,
                "command_account_mismatch_count": 0,
                "reservation_v1_account_mismatch_count": 0,
                "reservation_v2_binding_mismatch_count": 0,
                "outbox_v1_account_mismatch_count": 0,
                "outbox_v2_binding_mismatch_count": 0,
            }
        ],
        # Channel-B identity is its own authority now: the reconciler reads this
        # collection, never an identifier overlaid on the legacy binding row.
        "account_binding_identity": [
            {
                "executor_id": identity["executor_id"],
                "broker_server": identity["broker_server"],
                "execution_mode": "DEMO",
                "key_id": "disposable-identity",
                "scheme": account_binding.SCHEME,
                "contract_version": account_binding.VERSION,
                "algorithm": account_binding.ALGORITHM,
                "identifier": identity["account_binding_identifier"],
                "binding_source": account_binding.DATABASE_SOURCE,
                "generated_at": now.isoformat(),
                "retired_at": None,
                "producer_version": "channel-b-account-binding-identity-v1",
            }
        ],
        "backend_identity": [identity],
        "execution_ledger": [],
        "broker_mirror": [],
    }
    return database, broker, start, now


def fixture_attestation(identity: dict[str, Any]) -> dict[str, Any]:
    database, broker, start, end = collected_fixture(identity)
    return attest_collected_reconciliation(database=database, broker=broker, window_from=start, window_to=end)
