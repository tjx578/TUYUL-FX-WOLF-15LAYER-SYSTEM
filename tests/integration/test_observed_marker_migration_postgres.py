"""Exact historical-marker upgrade, on a runner-bound disposable PostgreSQL only."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from contracts.mt5_execution_protocol import build_signed_execution_envelope
from tests.test_mt5_engineering_demo_canary import EXECUTOR_ID, SECRET, _command, _executor, _request

pytestmark = [pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]
OBSERVED_MARKER = "20260823_01"
TARGET_HEAD = "20260908_01"
HISTORICAL_TIME = datetime(2026, 9, 1, 12, tzinfo=UTC)
TERMINAL_STATES = ("REJECTED", "FILLED", "CANCELLED", "COMPLETED", "EXPIRED", "SHADOW_COMPLETED", "SHADOW_REJECTED")
NEW_TABLES = (
    "strategy_5scr_analysis_admissions_v1",
    "strategy_5scr_analysis_admission_evaluations_v1",
    "strategy_5scr_analysis_evidence_jobs_v1",
    "strategy_5scr_analysis_evidence_snapshots_v1",
    "engineering_demo_canary_authority_packets",
    "direct_broker_reconciliation_receipts",
    "executor_mode_transition_authority_packets",
    "executor_mode_transition_receipts",
)
NEW_COLUMNS = {
    "authority_packet_sha256",
    "command_content_sha256",
    "legacy_authority_exempt",
    "legacy_authority_classified_at",
}


def _synthetic_row(label: str, state: str, *, terminal: bool) -> dict:
    request = _request(
        canary_id="migration-" + label,
        command_id=uuid4(),
        issued_at_utc=HISTORICAL_TIME,
        expires_at_utc=HISTORICAL_TIME + timedelta(seconds=90),
    )
    signed = _command(request=request)
    envelope = build_signed_execution_envelope(signed, root_secret=SECRET, key_id="d0-test-key")
    payload = signed.model_dump(mode="json")
    return {
        "command_id": signed.command_id,
        "executor_id": signed.executor_binding.executor_id,
        "account_id": signed.executor_binding.account_id,
        "source_event": "ENGINEERING_DEMO_CANARY",
        "source_signal_id": None,
        "source_signal_hash": None,
        "acceptance_run_id": None,
        "operator_authority": None,
        "acceptance_purpose": None,
        "engineering_canary_id": signed.source.canary_id,
        "canary_operator_authority": signed.source.operator_authority,
        "canary_purpose": signed.source.purpose,
        "idempotency_key": signed.idempotency_key,
        "revision": signed.revision,
        "action": signed.action.value,
        "payload": payload,
        "payload_hash": envelope.payload_sha256,
        "state": state,
        "issued_at": signed.issued_at_utc,
        "not_before": signed.not_before_utc,
        "expires_at": signed.expires_at_utc,
        "terminal_at": HISTORICAL_TIME + timedelta(seconds=60) if terminal else None,
        "wire_format": envelope.wire_version,
        "payload_encoding": envelope.payload_encoding,
        "signed_payload_b64": envelope.payload_b64,
        "signed_payload_sha256": envelope.payload_sha256,
        "signature_algorithm": envelope.algorithm,
        "signature_key_id": envelope.key_id,
        "signature_value": envelope.signature,
    }


def _insert_command(connection, row: dict) -> None:
    # Inserts only actual historical columns. No final schema, disabled trigger,
    # relaxed CHECK, migration stamp, or invented authority packet is used.
    statement = sql.SQL("INSERT INTO public.execution_commands ({}) VALUES ({})").format(
        sql.SQL(",").join(map(sql.Identifier, row)), sql.SQL(",").join(sql.Placeholder() for _ in row)
    )
    values = [Jsonb(value) if key == "payload" else value for key, value in row.items()]
    connection.execute(statement, values)


def _seed(connection, rows: list[dict]) -> None:
    executor = _executor()
    connection.execute(
        "INSERT INTO public.ea_agents (id,agent_name,ea_class,ea_subtype,execution_mode,reporter_mode,status,locked) "
        "VALUES (%s,'synthetic migration history','PRIMARY','EDUMB','DEMO','FULL','OFFLINE',false)",
        (EXECUTOR_ID,),
    )
    connection.execute(
        "INSERT INTO public.executor_instances (executor_id,account_id,login_hash,broker_server,terminal_build,"
        "ea_version,protocol_version,execution_mode,status,last_heartbeat_at) "
        "VALUES (%s,%s,%s,%s,4500,%s,%s,'DEMO','OFFLINE',%s)",
        (
            EXECUTOR_ID,
            executor["account_id"],
            executor["login_hash"],
            executor["broker_server"],
            executor["ea_version"],
            executor["protocol_version"],
            HISTORICAL_TIME,
        ),
    )
    for row in rows:
        _insert_command(connection, row)
        is_terminal = row["terminal_at"] is not None
        connection.execute(
            "INSERT INTO public.engineering_demo_canary_windows "
            "(canary_id,command_id,executor_id,account_id,broker_server,canonical_symbol,broker_symbol,"
            "state,max_broker_effects,expires_at,terminal_at) VALUES (%s,%s,%s,%s,%s,'EURUSD','EURUSD',%s,1,%s,%s)",
            (
                row["engineering_canary_id"],
                row["command_id"],
                EXECUTOR_ID,
                row["account_id"],
                executor["broker_server"],
                "CLOSED" if is_terminal else "QUEUED",
                row["expires_at"],
                row["terminal_at"],
            ),
        )


def _snapshot(connection) -> dict:
    return {
        "versions": [
            row["version_num"]
            for row in connection.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
        ],
        "commands": list(connection.execute("SELECT * FROM public.execution_commands ORDER BY command_id")),
        "windows": list(connection.execute("SELECT * FROM public.engineering_demo_canary_windows ORDER BY canary_id")),
        "columns": [
            row["column_name"]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                "AND table_name='execution_commands' ORDER BY ordinal_position"
            )
        ],
        "new_tables": [
            row["name"]
            for row in connection.execute(
                "SELECT table_name AS name FROM information_schema.tables WHERE table_schema='public' "
                "AND table_name=ANY(%s) ORDER BY table_name",
                (list(NEW_TABLES),),
            )
        ],
    }


def _persist(name: str, evidence: dict) -> None:
    root = Path(os.environ["WOLF15_MIGRATION_TEST_EVIDENCE_DIR"]).resolve(strict=True)
    if root.drive.upper() != "D:":
        raise ValueError("campaign evidence must remain on D")
    with (root / (name + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True, indent=2, default=str)
        stream.write("\n")


@pytest.fixture
def historical_database(monkeypatch):
    if os.environ.get("WOLF15_RUN_OBSERVED_MARKER_MIGRATION") != "1":
        pytest.skip("requires the separately authorized disposable PostgreSQL campaign")
    locator = Path(os.environ["WOLF15_MIGRATION_TEST_CONFIG"]).resolve(strict=True)
    binding = json.loads(locator.read_text())
    if binding.get("schema") != "wolf15.disposable-marker-pg/v1" or binding.get("host") != "127.0.0.1":
        pytest.fail("only a loopback runner-bound disposable PostgreSQL target is accepted")
    if binding.get("database_prefix") != "w15_marker_" or binding.get("production") is not False:
        pytest.fail("disposable database scope was not bound")
    evidence = locator.parent / "cases"
    evidence.mkdir(exist_ok=True)
    monkeypatch.setenv("WOLF15_MIGRATION_TEST_EVIDENCE_DIR", str(evidence))
    name = binding["database_prefix"] + uuid4().hex[:16]
    params = {
        "host": "127.0.0.1",
        "port": int(binding["port"]),
        "user": "postgres",
        "connect_timeout": 3,
        "options": "-c statement_timeout=30000 -c lock_timeout=5000 -c search_path=public",
        "sslmode": "disable",
    }
    with psycopg.connect(**params, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    # Schema ownership and rollback are provided by the real Alembic env.py.
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+psycopg://postgres@127.0.0.1:{params['port']}/{name}?sslmode=disable"
    )
    monkeypatch.setenv("PGOPTIONS", params["options"])
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "storage" / "migrations"))
    command.upgrade(config, OBSERVED_MARKER)
    with psycopg.connect(**params, dbname=name, autocommit=True, row_factory=dict_row) as connection:
        initial = _snapshot(connection)
        assert initial["versions"] == [OBSERVED_MARKER]
        assert not initial["new_tables"] and not NEW_COLUMNS.intersection(initial["columns"])
        yield connection, config
    # All isolated databases remain until the runner removes its one tmpfs
    # container; no generic DROP DATABASE or evidence-erasing cleanup is used.


def test_terminal_history_survives_upgrade_and_becomes_immutable(historical_database):
    connection, config = historical_database
    rows = [_synthetic_row(state.lower(), state, terminal=True) for state in TERMINAL_STATES]
    with connection.transaction():
        _seed(connection, rows)
    before = _snapshot(connection)
    _persist("terminal-before", before)
    started = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    command.upgrade(config, "head")
    finished = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    after = _snapshot(connection)
    assert after["versions"] == [TARGET_HEAD]
    assert set(after["new_tables"]) == set(NEW_TABLES)
    assert after["windows"] == before["windows"]
    assert len(after["commands"]) == len(TERMINAL_STATES)
    classified_times = set()
    for old, new in zip(before["commands"], after["commands"], strict=True):
        assert {key: value for key, value in new.items() if key not in NEW_COLUMNS} == old
        assert new["authority_packet_sha256"] is None and new["command_content_sha256"] is None
        assert new["legacy_authority_exempt"] is True
        assert started <= new["legacy_authority_classified_at"] <= finished
        classified_times.add(new["legacy_authority_classified_at"])
    assert len(classified_times) == 1
    for statement in (
        "UPDATE public.execution_commands SET state='COMPLETED' WHERE command_id=%s",
        "UPDATE public.execution_commands SET legacy_authority_exempt=false WHERE command_id=%s",
        "DELETE FROM public.execution_commands WHERE command_id=%s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation) as error, connection.transaction():
            connection.execute(statement, (rows[0]["command_id"],))
        assert error.value.diag.constraint_name == "ck_demo_legacy_command_immutable"
    forged = _synthetic_row("forged-exemption", "COMPLETED", terminal=True)
    forged.update(legacy_authority_exempt=True, legacy_authority_classified_at=HISTORICAL_TIME)
    with pytest.raises(psycopg.errors.CheckViolation) as error, connection.transaction():
        _insert_command(connection, forged)
    assert error.value.diag.constraint_name == "ck_demo_legacy_authority_insert_forbidden"
    assert _snapshot(connection) == after
    _persist("terminal-result", {"verdict": "PASS_REAL_POSTGRES_UPGRADE_AND_IMMUTABILITY", "after": after})


@pytest.mark.parametrize(
    ("state", "terminal"),
    [("QUEUED", False), ("QUEUED", True), ("FILLED", False)],
    ids=["nonterminal", "nonterminal-despite-terminal-timestamp", "terminal-state-null-terminal-at"],
)
def test_ambiguous_history_aborts_upgrade_and_preserves_original_rows(historical_database, state, terminal):
    connection, config = historical_database
    rows = [
        _synthetic_row("terminal-control", "COMPLETED", terminal=True),
        _synthetic_row("ambiguous", state, terminal=terminal),
    ]
    with connection.transaction():
        _seed(connection, rows)
    before = _snapshot(connection)
    case = state.lower() + ("-with-terminal-time" if terminal else "-without-terminal-time")
    _persist(case + "-before", before)
    with pytest.raises(DBAPIError) as error:
        command.upgrade(config, "head")
    assert error.value.orig.sqlstate == "23514"
    assert error.value.orig.diag.constraint_name == "ck_demo_historical_terminal_required"
    assert _snapshot(connection) == before
    _persist(
        case + "-result",
        {
            "verdict": "PASS_REAL_POSTGRES_ABORT_AND_PRESERVATION",
            "after": _snapshot(connection),
            "sqlstate": "23514",
            "constraint": "ck_demo_historical_terminal_required",
        },
    )
