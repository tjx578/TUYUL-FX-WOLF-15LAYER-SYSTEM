from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ops.mt5_mcp import account_binding, reconcile

WINDOW_TO = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
WINDOW_FROM = WINDOW_TO - timedelta(days=7)
TEST_KEY = b"k" * 32
TEST_KEY_ID = "audit-2026-01"
DIRECT_IDENTIFIER = account_binding.identifier(
    secret_key=TEST_KEY,
    key_id=TEST_KEY_ID,
    login=12345678,
    server="Broker-Demo",
)


def _payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "measurement_state": "MEASURED" if records else "MEASURED_EMPTY",
        "record_count": len(records),
        "source_record_count": len(records),
        "truncated": False,
        "records": records,
    }


def _broker(
    *,
    positions: list[dict[str, object]] | None = None,
    identifier: str = DIRECT_IDENTIFIER,
    server: str = "Broker-Demo",
) -> dict[str, object]:
    account = _payload([{"server": "Broker-Demo"}])
    history_deals = _payload([])
    history_deals["window"] = {"from_utc": WINDOW_FROM.isoformat(), "to_utc": WINDOW_TO.isoformat()}
    history_orders = _payload([])
    history_orders["window"] = {"from_utc": WINDOW_FROM.isoformat(), "to_utc": WINDOW_TO.isoformat()}
    broker = {
        "tool_surface_exact": True,
        "window": {"from_utc": WINDOW_FROM.isoformat(), "to_utc": WINDOW_TO.isoformat()},
        "snapshots": {
            "mt5_account_get": account,
            "mt5_positions_get": _payload(positions or []),
            "mt5_orders_get": _payload([]),
            "mt5_history_deals_get": history_deals,
            "mt5_history_orders_get": history_orders,
        },
    }
    for payload in broker["snapshots"].values():
        payload["account_binding"] = {
            "scheme": account_binding.SCHEME,
            "version": account_binding.VERSION,
            "algorithm": account_binding.ALGORITHM,
            "key_id": TEST_KEY_ID,
            "identifier": identifier,
            "server": server,
            "company": "Broker",
        }
        payload["terminal"] = {
            "path_sha256": "f" * 64,
            "version": [500, 9999, "24 Aug 2026"],
        }
    return broker


def _database(
    *,
    mirror: list[dict[str, object]] | None = None,
    ledger: list[dict[str, object]] | None = None,
    account_identifier: str | None = None,
    account_identifier_source: str | None = None,
    broker_server: str = "Broker-Demo",
) -> dict[str, object]:
    executor_id = "11111111-1111-1111-1111-111111111111"
    return {
        "measured": True,
        "truncated": False,
        "mutation_evidence": {"xid_unassigned": True, "changed_tuples": 0},
        "executor_identity": [{"executor_id": executor_id, "revoked_at": None}],
        "executor_freshness": [
            {
                "executor_id": executor_id,
                "status": "ONLINE",
                "heartbeat_age_seconds": 5,
                "snapshot_age_seconds": 5,
                "latest_snapshot_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            }
        ],
        "account_binding": [
            {
                "executor_id": executor_id,
                "broker_server": broker_server,
                "latest_snapshot_account_matches": True,
                "command_account_mismatch_count": 0,
                "reservation_v1_account_mismatch_count": 0,
                "reservation_v2_binding_mismatch_count": 0,
                "outbox_v1_account_mismatch_count": 0,
                "outbox_v2_binding_mismatch_count": 0,
                **(
                    {"account_binding_identifier": account_identifier}
                    if account_identifier is not None
                    else {}
                ),
                **(
                    {"account_binding_source": account_identifier_source}
                    if account_identifier_source is not None
                    else {}
                ),
            }
        ],
        "broker_mirror": mirror or [],
        "execution_ledger": ledger or [],
    }


def test_empty_measured_snapshots_do_not_claim_account_bound_reconciliation() -> None:
    report = reconcile.reconcile_snapshots(
        database=_database(),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["DIRECT_BROKER_STATE"] == "MEASURED"
    assert report["DATABASE_MIRROR_STATE"] == "MEASURED"
    assert report["DATABASE_PRODUCTION_MUTATION_COUNT"] == 0
    assert report["ACCOUNT_BINDING_STATE"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert report["BROKER_RECONCILIATION"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert report["B-B16"] == "EXECUTED_INCOMPLETE"
    assert report["PRODUCTION_READY"] is False


def test_trusted_matching_hmac_identifier_closes_account_binding_only() -> None:
    report = reconcile.reconcile_snapshots(
        database=_database(
            account_identifier=DIRECT_IDENTIFIER,
            account_identifier_source=account_binding.DATABASE_SOURCE,
        ),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["ACCOUNT_BINDING_STATE"] == "MATCHED"
    assert report["account_binding_evidence"]["direct_identity_consistent"] is True
    assert report["account_binding_evidence"]["direct_tool_identity_count"] == 5
    assert report["account_binding_evidence"]["direct_account_identifier_match"] is True
    assert report["BROKER_RECONCILIATION"] == "MATCHED"
    assert report["B-B16"] == "PASS"
    assert report["EXECUTION_READY"] is False
    assert report["PRODUCTION_READY"] is False


def test_identifier_mismatch_and_untrusted_source_fail_closed() -> None:
    other_identifier = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=87654321,
        server="Broker-Demo",
    )
    mismatch = reconcile.reconcile_snapshots(
        database=_database(
            account_identifier=other_identifier,
            account_identifier_source=account_binding.DATABASE_SOURCE,
        ),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )
    untrusted = reconcile.reconcile_snapshots(
        database=_database(
            account_identifier=DIRECT_IDENTIFIER,
            account_identifier_source="MANUAL_INPUT",
        ),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert mismatch["ACCOUNT_BINDING_STATE"] == "MISMATCH"
    assert mismatch["B-B16"] == "EXECUTED_BLOCKED"
    assert untrusted["ACCOUNT_BINDING_STATE"] == "UNTRUSTED_DATABASE_IDENTIFIER"
    assert untrusted["B-B16"] == "EXECUTED_BLOCKED"


def test_all_five_mt5_calls_must_have_one_account_and_terminal_identity() -> None:
    broker = _broker()
    broker["snapshots"]["mt5_orders_get"]["terminal"]["version"] = [500, 10000, "24 Aug 2026"]

    report = reconcile.reconcile_snapshots(
        database=_database(
            account_identifier=DIRECT_IDENTIFIER,
            account_identifier_source=account_binding.DATABASE_SOURCE,
        ),
        broker=broker,
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["ACCOUNT_BINDING_STATE"] == "INCONSISTENT_DIRECT_IDENTITY"
    assert report["account_binding_evidence"]["direct_identity_consistent"] is False
    assert report["BROKER_RECONCILIATION"] == "MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_broker_server_comparison_is_case_sensitive() -> None:
    report = reconcile.reconcile_snapshots(
        database=_database(
            account_identifier=DIRECT_IDENTIFIER,
            account_identifier_source=account_binding.DATABASE_SOURCE,
            broker_server="broker-demo",
        ),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["ACCOUNT_BINDING_STATE"] == "MISMATCH"
    assert report["account_binding_evidence"]["broker_server_candidate_count"] == 0
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_stale_or_missing_executor_freshness_blocks_account_binding() -> None:
    database = _database(
        account_identifier=DIRECT_IDENTIFIER,
        account_identifier_source=account_binding.DATABASE_SOURCE,
    )
    database["executor_freshness"][0]["heartbeat_age_seconds"] = 31

    report = reconcile.reconcile_snapshots(
        database=database,
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["ACCOUNT_BINDING_STATE"] == "STALE_OR_AMBIGUOUS_EXECUTOR"
    assert report["account_binding_evidence"]["online_fresh_executor_count"] == 0
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_ticket_match_is_bidirectional_and_raw_ticket_is_not_reported() -> None:
    ticket = 987654321
    command_id = "22222222-2222-2222-2222-222222222222"
    position = {
        "ticket": ticket,
        "symbol": "EURUSD",
        "magic": 42,
        "time_msc_utc": (WINDOW_TO - timedelta(hours=1)).isoformat(),
    }
    mirror = [
        {
            "command_id": command_id,
            "entity_type": "POSITION",
            "broker_ticket": ticket,
            "symbol": "EURUSD",
            "last_seen_at": WINDOW_TO - timedelta(minutes=5),
            "command_terminal_at": None,
        }
    ]
    ledger = [
        {
            "command_id": command_id,
            "source_event": "signal_json",
            "signed_wire_hash_matches": True,
            "risk_binding_matches": True,
            "final_signal_binding_matches": True,
        }
    ]

    report = reconcile.reconcile_snapshots(
        database=_database(mirror=mirror, ledger=ledger),
        broker=_broker(positions=[position]),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["comparison"]["broker_to_database"]["classification_counts"] == {"MATCHED": 1}
    assert report["comparison"]["database_to_broker"]["classification_counts"] == {"MATCHED": 1}
    assert str(ticket) not in json.dumps(report)


def test_unavailable_broker_evidence_never_becomes_measured_empty_or_zero() -> None:
    broker = _broker()
    broker["snapshots"]["mt5_positions_get"] = {
        "measurement_state": "NOT_MEASURED",
        "record_count": None,
        "source_record_count": None,
        "truncated": None,
        "records": None,
    }

    report = reconcile.reconcile_snapshots(
        database=_database(),
        broker=broker,
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["DIRECT_BROKER_STATE"] == "NOT_MEASURED"
    assert report["broker_measurements"]["mt5_positions_get"]["record_count"] is None
    assert report["BROKER_RECONCILIATION"] == "NOT_MEASURED"
    assert report["B-B16"] == "NOT_EXECUTED"


def test_unmatched_entities_remain_explicit_and_block_the_gate() -> None:
    position = {
        "ticket": 333,
        "symbol": "USDJPY",
        "magic": 17,
        "time_msc_utc": (WINDOW_TO - timedelta(hours=1)).isoformat(),
    }
    mirror = [
        {
            "command_id": "44444444-4444-4444-4444-444444444444",
            "entity_type": "DEAL",
            "broker_ticket": 444,
            "symbol": "GBPUSD",
            "last_seen_at": WINDOW_TO - timedelta(hours=2),
            "command_terminal_at": None,
        }
    ]

    report = reconcile.reconcile_snapshots(
        database=_database(mirror=mirror),
        broker=_broker(positions=[position]),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )

    assert report["comparison"]["broker_to_database"]["classification_counts"] == {"UNATTRIBUTED": 1}
    assert report["comparison"]["database_to_broker"]["classification_counts"] == {"ORPHAN": 1}
    assert report["BROKER_RECONCILIATION"] == "INCOMPLETE_ACCOUNT_IDENTIFIER_WITH_ENTITY_MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_database_queries_are_select_only() -> None:
    queries = (
        reconcile.AUDIT_SESSION_SQL,
        reconcile.IDENTITY_SQL,
        reconcile.FRESHNESS_SQL,
        reconcile.BINDING_SQL,
        reconcile.CONTAINMENT_SQL,
        reconcile.LEDGER_SQL,
        reconcile.MIRROR_SQL,
        reconcile.MUTATION_SQL,
    )
    assert all(query.lstrip().upper().startswith("SELECT") for query in queries)
    forbidden = ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "ALTER ", "CREATE ", "DROP ")
    assert all(token not in query.upper() for query in queries for token in forbidden)


def test_ledger_query_uses_interval_overlap_not_created_at_only() -> None:
    normalized = " ".join(reconcile.LEDGER_SQL.split())

    assert "created_at < $2" in normalized
    assert "terminal_at IS NULL OR terminal_at >= $1" in normalized


def test_database_snapshot_stops_before_views_on_audit_session_mismatch(monkeypatch: object) -> None:
    class FakeTransaction:
        def __init__(self) -> None:
            self.started = False
            self.rolled_back = False

        async def start(self) -> None:
            self.started = True

        async def rollback(self) -> None:
            self.rolled_back = True

    class FakeConnection:
        def __init__(self) -> None:
            self.transaction_state = FakeTransaction()
            self.closed = False

        def transaction(self, *, isolation: str, readonly: bool) -> FakeTransaction:
            assert isolation == "repeatable_read"
            assert readonly is True
            return self.transaction_state

        async def fetchrow(self, query: str) -> dict[str, object]:
            assert query == reconcile.AUDIT_SESSION_SQL
            return {
                "current_role": "application_writer",
                "transaction_read_only": True,
                "transaction_isolation": "repeatable read",
            }

        async def fetch(self, *_args: object) -> list[dict[str, object]]:
            raise AssertionError("audit views must not be read after a role mismatch")

        async def close(self) -> None:
            self.closed = True

    connection = FakeConnection()

    class FakeAsyncpg:
        @staticmethod
        async def connect(*, dsn: str, command_timeout: int) -> FakeConnection:
            assert dsn == "postgresql://redacted"
            assert command_timeout == 15
            return connection

    monkeypatch.setattr(reconcile.importlib, "import_module", lambda name: FakeAsyncpg)

    result = asyncio.run(
        reconcile._database_snapshot(
            "postgresql://redacted",
            window_from=WINDOW_FROM,
            window_to=WINDOW_TO,
        )
    )

    assert result["measured"] is False
    assert result["error_type"] == "DATABASE_AUDIT_SESSION_MISMATCH"
    assert connection.transaction_state.started is True
    assert connection.transaction_state.rolled_back is True
    assert connection.closed is True


def test_cli_requires_local_hmac_environment_before_any_collection(
    monkeypatch: object, capsys: object, tmp_path: Path
) -> None:
    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgresql://must-not-appear")
    monkeypatch.delenv(account_binding.KEY_ENV, raising=False)
    monkeypatch.delenv(account_binding.KEY_ID_ENV, raising=False)

    result = reconcile.main(tmp_path)
    output = capsys.readouterr().out

    assert result == 2
    assert "ACCOUNT_BINDING_KEY_ENCODING_INVALID" in output
    assert "postgresql://must-not-appear" not in output
    assert '"DIRECT_BROKER_STATE": "NOT_MEASURED"' in output
    assert '"B-B16": "NOT_EXECUTED"' in output


def test_secure_launcher_requires_local_key_environment_and_v2_report() -> None:
    launcher = Path("scripts/run_channel_b_reconciliation.ps1").read_text(encoding="utf-8")

    assert "$env:WOLF15_ACCOUNT_BINDING_KEY_B64URL" in launcher
    assert "$env:WOLF15_ACCOUNT_BINDING_KEY_ID" in launcher
    assert 'schema_version = "wolf15.channel-b-reconciliation.v2"' in launcher
