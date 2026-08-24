"""Bounded, fail-closed Channel A/Channel B reconciliation.

The database side reads only the six approved ``wolf15_audit`` views inside a
repeatable-read, read-only transaction.  The broker side is collected through
the configured Native MT5 MCP tool surface.  Reports contain fingerprints and
counts, never the database URL, password, raw MT5 login, or raw broker tickets.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ops.mt5_mcp import account_binding

MEASURED_STATES: Final = frozenset({"MEASURED", "MEASURED_EMPTY"})
ENTITY_TYPES: Final = ("POSITION", "ORDER", "DEAL")
MAX_DATABASE_ROWS: Final = 1_000
HISTORY_DAYS: Final = 7
EXPECTED_AUDIT_ROLE: Final = "wolf15_auditor"
MAX_RUNTIME_AGE_SECONDS: Final = 30

AUDIT_SESSION_SQL: Final = """
    SELECT current_user AS current_role,
           current_setting('transaction_read_only')::boolean AS transaction_read_only,
           current_setting('transaction_isolation') AS transaction_isolation
"""

IDENTITY_SQL: Final = """
    SELECT * FROM wolf15_audit.executor_identity_v1
    ORDER BY executor_id
    LIMIT $1
"""
FRESHNESS_SQL: Final = """
    SELECT * FROM wolf15_audit.executor_freshness_v1
    ORDER BY executor_id
    LIMIT $1
"""
BINDING_SQL: Final = """
    SELECT * FROM wolf15_audit.account_binding_v1
    ORDER BY executor_id
    LIMIT $1
"""
CONTAINMENT_SQL: Final = "SELECT * FROM wolf15_audit.execution_containment_v1 LIMIT 2"
LEDGER_SQL: Final = """
    SELECT *
      FROM wolf15_audit.execution_ledger_v1
     WHERE created_at < $2
       AND (terminal_at IS NULL OR terminal_at >= $1)
     ORDER BY created_at, command_id
     LIMIT $3
"""
MIRROR_SQL: Final = """
    SELECT *
      FROM wolf15_audit.broker_mirror_v1
     WHERE (first_seen_at < $2 AND last_seen_at >= $1)
        OR command_terminal_at IS NULL
     ORDER BY first_seen_at, broker_entity_id
     LIMIT $3
"""
MUTATION_SQL: Final = """
    SELECT pg_catalog.pg_current_xact_id_if_assigned() IS NULL AS xid_unassigned,
           coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0)::bigint AS changed_tuples
      FROM pg_catalog.pg_stat_xact_user_tables
"""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return dict(value)


def _fingerprint(entity_type: str, ticket: Any) -> str:
    material = f"{entity_type}:{ticket}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def _normalized_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for field in ("time_msc_utc", "time_setup_msc_utc", "time_utc", "time_setup_utc"):
        raw = record.get(field)
        if not isinstance(raw, str):
            continue
        with suppress(ValueError):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
    return None


def _direct_entities(snapshots: Mapping[str, Mapping[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    entities: dict[tuple[str, int], dict[str, Any]] = {}
    sources = (
        ("POSITION", "CURRENT", "mt5_positions_get"),
        ("ORDER", "CURRENT", "mt5_orders_get"),
        ("DEAL", "HISTORY", "mt5_history_deals_get"),
        ("ORDER", "HISTORY", "mt5_history_orders_get"),
    )
    for entity_type, source, tool_name in sources:
        payload = snapshots.get(tool_name, {})
        records = payload.get("records")
        if not isinstance(records, list):
            continue
        for raw in records:
            if not isinstance(raw, Mapping):
                continue
            with suppress(TypeError, ValueError):
                ticket = int(raw.get("ticket"))
                key = (entity_type, ticket)
                item = entities.setdefault(
                    key,
                    {
                        "entity_type": entity_type,
                        "ticket": ticket,
                        "symbol": _normalized_symbol(raw.get("symbol")),
                        "magic": raw.get("magic"),
                        "observed_time": _record_time(raw),
                        "sources": set(),
                    },
                )
                item["sources"].add(source)
    return entities


def _mirror_entities(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    entities: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in rows:
        row = _mapping(raw)
        entity_type = str(row.get("entity_type") or "").upper()
        if entity_type not in ENTITY_TYPES:
            continue
        with suppress(TypeError, ValueError):
            ticket = int(row.get("broker_ticket"))
            entities.setdefault((entity_type, ticket), []).append(row)
    return entities


def _ledger_holds(row: Mapping[str, Any] | None) -> bool:
    if row is None or row.get("signed_wire_hash_matches") is not True:
        return False
    if row.get("source_event") == "signal_json":
        return row.get("risk_binding_matches") is True and row.get("final_signal_binding_matches") is True
    return True


def _classify_entities(
    *,
    direct: Mapping[tuple[str, int], dict[str, Any]],
    mirrors: Mapping[tuple[str, int], list[dict[str, Any]]],
    ledger_rows: Sequence[Mapping[str, Any]],
    window_from: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ledger = {str(row.get("command_id")): row for row in ledger_rows}
    broker_to_database: list[dict[str, Any]] = []
    database_to_broker: list[dict[str, Any]] = []

    for key, entity in sorted(direct.items()):
        matches = mirrors.get(key, [])
        classification: str
        if len(matches) > 1:
            classification = "AMBIGUOUS"
        elif len(matches) == 1:
            mirror = matches[0]
            symbol_matches = _normalized_symbol(mirror.get("symbol")) == entity["symbol"]
            command = ledger.get(str(mirror.get("command_id")))
            classification = "MATCHED" if symbol_matches and _ledger_holds(command) else "AMBIGUOUS"
        elif entity.get("observed_time") is not None and entity["observed_time"] < window_from:
            classification = "PREEXISTING"
        elif entity.get("magic") == 0:
            classification = "MANUAL_OR_EXTERNAL"
        else:
            classification = "UNATTRIBUTED"
        broker_to_database.append(
            {
                "entity_type": key[0],
                "entity_fingerprint": _fingerprint(*key),
                "symbol": entity["symbol"],
                "sources": sorted(entity["sources"]),
                "classification": classification,
            }
        )

    for key, rows in sorted(mirrors.items()):
        direct_entity = direct.get(key)
        for row in rows:
            if len(rows) > 1:
                classification = "AMBIGUOUS"
            elif direct_entity is not None:
                symbol_matches = _normalized_symbol(row.get("symbol")) == direct_entity["symbol"]
                classification = "MATCHED" if symbol_matches and _ledger_holds(
                    ledger.get(str(row.get("command_id")))
                ) else "AMBIGUOUS"
            else:
                last_seen = row.get("last_seen_at")
                terminal_at = row.get("command_terminal_at")
                classification = (
                    "PREEXISTING"
                    if isinstance(last_seen, datetime) and last_seen < window_from and terminal_at is not None
                    else "ORPHAN"
                )
            database_to_broker.append(
                {
                    "entity_type": key[0],
                    "entity_fingerprint": _fingerprint(*key),
                    "symbol": _normalized_symbol(row.get("symbol")),
                    "classification": classification,
                }
            )
    return broker_to_database, database_to_broker


def _measurement_summary(
    broker: Mapping[str, Any], *, window_from: datetime, window_to: datetime
) -> tuple[dict[str, Any], bool]:
    snapshots = broker.get("snapshots")
    if not isinstance(snapshots, Mapping):
        return {}, False
    summary: dict[str, Any] = {}
    expected_window = {"from_utc": _iso(window_from), "to_utc": _iso(window_to)}
    measured = bool(broker.get("tool_surface_exact")) and broker.get("window") == expected_window
    for tool_name in (
        "mt5_account_get",
        "mt5_positions_get",
        "mt5_orders_get",
        "mt5_history_deals_get",
        "mt5_history_orders_get",
    ):
        payload = snapshots.get(tool_name)
        if not isinstance(payload, Mapping):
            summary[tool_name] = {"measurement_state": "NOT_MEASURED", "record_count": None}
            measured = False
            continue
        state = payload.get("measurement_state", "NOT_MEASURED")
        truncated = payload.get("truncated")
        summary[tool_name] = {
            "measurement_state": state,
            "record_count": payload.get("record_count"),
            "source_record_count": payload.get("source_record_count"),
            "truncated": truncated,
        }
        if state not in MEASURED_STATES or truncated is not False:
            measured = False
        if tool_name.startswith("mt5_history_") and payload.get("window") != expected_window:
            measured = False
    return summary, measured


def _direct_identity(
    broker: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    snapshots = broker.get("snapshots")
    if not isinstance(snapshots, Mapping):
        return "NOT_MEASURED", {"direct_identity_consistent": "NOT_MEASURED"}, None

    identities: list[dict[str, Any]] = []
    for tool_name in (
        "mt5_account_get",
        "mt5_positions_get",
        "mt5_orders_get",
        "mt5_history_deals_get",
        "mt5_history_orders_get",
    ):
        payload = snapshots.get(tool_name)
        if not isinstance(payload, Mapping) or payload.get("measurement_state") not in MEASURED_STATES:
            return "NOT_MEASURED", {"direct_identity_consistent": "NOT_MEASURED"}, None
        binding = payload.get("account_binding")
        terminal = payload.get("terminal")
        if not isinstance(binding, Mapping) or not isinstance(terminal, Mapping):
            return "NOT_MEASURED", {"direct_identity_consistent": "NOT_MEASURED"}, None
        identifier_value = binding.get("identifier")
        try:
            parsed_key_id = account_binding.identifier_key_id(identifier_value)
            account_binding.canonical_server(binding.get("server"))
        except account_binding.AccountBindingError:
            return "INVALID_DIRECT_IDENTITY", {"direct_identity_consistent": False}, None
        if (
            binding.get("scheme") != account_binding.SCHEME
            or binding.get("version") != account_binding.VERSION
            or binding.get("algorithm") != account_binding.ALGORITHM
            or binding.get("key_id") != parsed_key_id
        ):
            return "INVALID_DIRECT_IDENTITY", {"direct_identity_consistent": False}, None
        path_sha256 = terminal.get("path_sha256")
        version = terminal.get("version")
        if (
            not isinstance(path_sha256, str)
            or len(path_sha256) != 64
            or any(character not in "0123456789abcdef" for character in path_sha256)
            or not isinstance(version, list)
            or len(version) < 2
        ):
            return "INVALID_DIRECT_IDENTITY", {"direct_identity_consistent": False}, None
        identities.append(
            {
                "identifier": identifier_value,
                "key_id": parsed_key_id,
                "server": binding.get("server"),
                "terminal_path_sha256": path_sha256,
                "terminal_version": version,
            }
        )

    direct = identities[0]
    if any(identity != direct for identity in identities[1:]):
        return (
            "INCONSISTENT_DIRECT_IDENTITY",
            {"direct_identity_consistent": False, "direct_tool_identity_count": len(identities)},
            None,
        )
    evidence = {
        "direct_identity_consistent": True,
        "direct_tool_identity_count": len(identities),
        "direct_key_id": direct["key_id"],
        "direct_account_identifier_prefix": str(direct["identifier"])[:24],
        "terminal_path_fingerprint_prefix": str(direct["terminal_path_sha256"])[:16],
        "terminal_build": direct["terminal_version"][1],
    }
    return "MEASURED", evidence, direct


def _account_binding(
    broker: Mapping[str, Any], database: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    direct_state, direct_evidence, direct = _direct_identity(broker)
    if direct_state != "MEASURED" or direct is None:
        return direct_state, {**direct_evidence, "direct_account_identifier_match": "NOT_MEASURED"}

    identities = database.get("executor_identity", [])
    freshness = database.get("executor_freshness", [])
    bindings = database.get("account_binding", [])
    active_ids = {
        str(row.get("executor_id"))
        for row in identities
        if isinstance(row, Mapping) and row.get("revoked_at") is None
    }
    fresh_ids = {
        str(row.get("executor_id"))
        for row in freshness
        if isinstance(row, Mapping)
        and str(row.get("executor_id")) in active_ids
        and row.get("status") == "ONLINE"
        and isinstance(row.get("heartbeat_age_seconds"), int)
        and -5 <= row["heartbeat_age_seconds"] <= MAX_RUNTIME_AGE_SECONDS
        and isinstance(row.get("snapshot_age_seconds"), int)
        and -5 <= row["snapshot_age_seconds"] <= MAX_RUNTIME_AGE_SECONDS
        and row.get("latest_snapshot_id") is not None
    }
    candidates = [
        row
        for row in bindings
        if isinstance(row, Mapping)
        and str(row.get("executor_id")) in fresh_ids
        and str(row.get("broker_server") or "") == direct["server"]
    ]
    internal_holds = False
    if len(candidates) == 1:
        row = candidates[0]
        mismatch_fields = (
            "command_account_mismatch_count",
            "reservation_v1_account_mismatch_count",
            "reservation_v2_binding_mismatch_count",
            "outbox_v1_account_mismatch_count",
            "outbox_v2_binding_mismatch_count",
        )
        internal_holds = row.get("latest_snapshot_account_matches") is True and all(
            int(row.get(field) or 0) == 0 for field in mismatch_fields
        )
    evidence: dict[str, Any] = {
        **direct_evidence,
        "active_executor_count": len(active_ids),
        "online_fresh_executor_count": len(fresh_ids),
        "broker_server_candidate_count": len(candidates),
        "broker_server_matches": len(candidates) == 1,
        "database_internal_binding_holds": internal_holds,
        "direct_account_identifier_match": "NOT_MEASURED_NOT_EXPOSED_BY_AUDIT_VIEW",
    }
    if len(candidates) > 1:
        return "AMBIGUOUS", evidence
    if len(fresh_ids) != 1:
        return "STALE_OR_AMBIGUOUS_EXECUTOR", evidence
    if len(candidates) == 0 or not internal_holds:
        return "MISMATCH", evidence

    candidate = candidates[0]
    database_identifier = candidate.get("account_binding_identifier")
    database_source = candidate.get("account_binding_source")
    if database_identifier is None:
        return "INCOMPLETE_ACCOUNT_IDENTIFIER", evidence
    if database_source != account_binding.DATABASE_SOURCE:
        evidence["database_identifier_source_trusted"] = False
        return "UNTRUSTED_DATABASE_IDENTIFIER", evidence
    evidence["database_identifier_source_trusted"] = True
    try:
        database_key_id = account_binding.identifier_key_id(database_identifier)
    except account_binding.AccountBindingError:
        evidence["database_identifier_contract_valid"] = False
        return "INVALID_DATABASE_IDENTIFIER", evidence
    evidence["database_identifier_contract_valid"] = True
    evidence["database_key_id"] = database_key_id
    evidence["direct_account_identifier_match"] = account_binding.identifiers_match(
        direct["identifier"], database_identifier
    )
    if database_key_id != direct["key_id"]:
        return "KEY_VERSION_MISMATCH", evidence
    return ("MATCHED", evidence) if evidence["direct_account_identifier_match"] else ("MISMATCH", evidence)


def reconcile_snapshots(
    *,
    database: Mapping[str, Any],
    broker: Mapping[str, Any],
    window_from: datetime,
    window_to: datetime,
) -> dict[str, Any]:
    measurements, broker_measured = _measurement_summary(
        broker,
        window_from=window_from,
        window_to=window_to,
    )
    database_measured = bool(database.get("measured")) and not bool(database.get("truncated"))
    mutation_evidence = database.get("mutation_evidence", {})
    zero_mutation = bool(
        isinstance(mutation_evidence, Mapping)
        and mutation_evidence.get("xid_unassigned") is True
        and int(mutation_evidence.get("changed_tuples") or 0) == 0
    )
    account_state, account_evidence = _account_binding(broker, database)

    snapshots = broker.get("snapshots", {})
    direct = _direct_entities(snapshots if isinstance(snapshots, Mapping) else {})
    mirrors = _mirror_entities(database.get("broker_mirror", []))
    broker_to_database, database_to_broker = _classify_entities(
        direct=direct,
        mirrors=mirrors,
        ledger_rows=database.get("execution_ledger", []),
        window_from=window_from,
    )
    b2d_counts = Counter(item["classification"] for item in broker_to_database)
    d2b_counts = Counter(item["classification"] for item in database_to_broker)
    hard_mismatches = sum(
        b2d_counts[name] + d2b_counts[name] for name in ("ORPHAN", "UNATTRIBUTED", "AMBIGUOUS")
    )
    review_items = b2d_counts["MANUAL_OR_EXTERNAL"] + d2b_counts["MANUAL_OR_EXTERNAL"]

    if not broker_measured or not database_measured or not zero_mutation:
        reconciliation = "NOT_MEASURED"
        gate = "NOT_EXECUTED" if not broker_measured or not database_measured else "FAIL_CLOSED"
    elif account_state == "MATCHED" and hard_mismatches:
        reconciliation = "ACCOUNT_BOUND_WITH_ENTITY_MISMATCH"
        gate = "EXECUTED_BLOCKED"
    elif account_state == "MATCHED" and review_items:
        reconciliation = "ACCOUNT_BOUND_WITH_REVIEW"
        gate = "EXECUTED_INCOMPLETE"
    elif account_state == "MATCHED":
        reconciliation = "MATCHED"
        gate = "PASS"
    elif account_state == "INCOMPLETE_ACCOUNT_IDENTIFIER" and hard_mismatches:
        reconciliation = "INCOMPLETE_ACCOUNT_IDENTIFIER_WITH_ENTITY_MISMATCH"
        gate = "EXECUTED_BLOCKED"
    elif account_state == "INCOMPLETE_ACCOUNT_IDENTIFIER" and review_items:
        reconciliation = "INCOMPLETE_ACCOUNT_IDENTIFIER_WITH_REVIEW"
        gate = "EXECUTED_INCOMPLETE"
    elif account_state == "INCOMPLETE_ACCOUNT_IDENTIFIER":
        reconciliation = "INCOMPLETE_ACCOUNT_IDENTIFIER"
        gate = "EXECUTED_INCOMPLETE"
    else:
        reconciliation = "MISMATCH" if account_state != "NOT_MEASURED" else "NOT_MEASURED"
        gate = "EXECUTED_BLOCKED"

    return {
        "schema_version": "wolf15.channel-b-reconciliation.v2",
        "window": {"from_utc": _iso(window_from), "to_utc": _iso(window_to)},
        "AUDIT_DATABASE_URL": "PRESENT",
        "DATABASE_MIRROR_STATE": "MEASURED" if database_measured else "NOT_MEASURED",
        "DIRECT_BROKER_STATE": "MEASURED" if broker_measured else "NOT_MEASURED",
        "DATABASE_PRODUCTION_MUTATION_COUNT": 0 if zero_mutation else "NOT_MEASURED",
        "ACCOUNT_BINDING_STATE": account_state,
        "account_binding_evidence": account_evidence,
        "broker_measurements": measurements,
        "database_measurements": {
            "audit_session": database.get("audit_session"),
            "executor_identity_rows": len(database.get("executor_identity", [])),
            "executor_freshness_rows": len(database.get("executor_freshness", [])),
            "account_binding_rows": len(database.get("account_binding", [])),
            "execution_containment_rows": len(database.get("execution_containment", [])),
            "execution_ledger_rows": len(database.get("execution_ledger", [])),
            "broker_mirror_rows": len(database.get("broker_mirror", [])),
            "truncated": database.get("truncated"),
        },
        "comparison": {
            "broker_to_database": {
                "classification_counts": dict(sorted(b2d_counts.items())),
                "entities": broker_to_database,
            },
            "database_to_broker": {
                "classification_counts": dict(sorted(d2b_counts.items())),
                "entities": database_to_broker,
            },
        },
        "BROKER_RECONCILIATION": reconciliation,
        "B-B16": gate,
        "EXECUTION_READY": False,
        "PRODUCTION_READY": False,
    }


def _clean_database_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [_mapping(row) for row in rows]


async def _database_snapshot(dsn: str, *, window_from: datetime, window_to: datetime) -> dict[str, Any]:
    asyncpg = importlib.import_module("asyncpg")
    connection: Any | None = None
    transaction: Any | None = None
    try:
        connection = await asyncpg.connect(dsn=dsn, command_timeout=15)
        transaction = connection.transaction(isolation="repeatable_read", readonly=True)
        await transaction.start()
        audit_session = _mapping(await connection.fetchrow(AUDIT_SESSION_SQL))
        if (
            audit_session.get("current_role") != EXPECTED_AUDIT_ROLE
            or audit_session.get("transaction_read_only") is not True
            or audit_session.get("transaction_isolation") != "repeatable read"
        ):
            return {
                "measured": False,
                "truncated": None,
                "error_type": "DATABASE_AUDIT_SESSION_MISMATCH",
                "audit_session": audit_session,
            }
        limit = MAX_DATABASE_ROWS + 1
        identity = await connection.fetch(IDENTITY_SQL, limit)
        freshness = await connection.fetch(FRESHNESS_SQL, limit)
        binding = await connection.fetch(BINDING_SQL, limit)
        containment = await connection.fetch(CONTAINMENT_SQL)
        ledger = await connection.fetch(LEDGER_SQL, window_from, window_to, limit)
        mirror = await connection.fetch(MIRROR_SQL, window_from, window_to, limit)
        mutation = _mapping(await connection.fetchrow(MUTATION_SQL))
        truncated = any(
            len(rows) > MAX_DATABASE_ROWS for rows in (identity, freshness, binding, ledger, mirror)
        ) or len(containment) > 1
        report = {
            "measured": True,
            "truncated": truncated,
            "executor_identity": _clean_database_rows(identity[:MAX_DATABASE_ROWS]),
            "executor_freshness": _clean_database_rows(freshness[:MAX_DATABASE_ROWS]),
            "account_binding": _clean_database_rows(binding[:MAX_DATABASE_ROWS]),
            "execution_containment": _clean_database_rows(containment[:1]),
            "execution_ledger": _clean_database_rows(ledger[:MAX_DATABASE_ROWS]),
            "broker_mirror": _clean_database_rows(mirror[:MAX_DATABASE_ROWS]),
            "mutation_evidence": mutation,
            "audit_session": audit_session,
        }
        await transaction.rollback()
        transaction = None
        return report
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "truncated": None, "error_type": type(exc).__name__}
    finally:
        if transaction is not None:
            with suppress(Exception):
                await transaction.rollback()
        if connection is not None:
            with suppress(Exception):
                await connection.close()


def _collector_command(config_path: Path, *, window_from: datetime, window_to: datetime) -> list[str]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    python_command = config["mcp_servers"]["native_mt5_readonly"]["command"]
    return [
        python_command,
        "-m",
        "ops.mt5_mcp.snapshot",
        "--from-utc",
        _iso(window_from),
        "--to-utc",
        _iso(window_to),
        "--config",
        str(config_path),
    ]


async def _broker_snapshot(
    config_path: Path, *, window_from: datetime, window_to: datetime, cwd: Path
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("AUDIT_DATABASE_URL", None)
    command = _collector_command(config_path, window_from=window_from, window_to=window_to)

    def invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )

    try:
        completed = await asyncio.to_thread(invoke)
        if completed.returncode != 0:
            return {"tool_surface_exact": False, "snapshots": {}, "error_type": "CollectorExitError"}
        payload = json.loads(completed.stdout)
        return payload if isinstance(payload, dict) else {"tool_surface_exact": False, "snapshots": {}}
    except Exception as exc:  # noqa: BLE001
        return {"tool_surface_exact": False, "snapshots": {}, "error_type": type(exc).__name__}


async def run_reconciliation(*, dsn: str, repo_root: Path, config_path: Path) -> dict[str, Any]:
    window_to = datetime.now(UTC)
    window_from = window_to - timedelta(days=HISTORY_DAYS)
    broker = await _broker_snapshot(
        config_path,
        window_from=window_from,
        window_to=window_to,
        cwd=repo_root,
    )
    database = await _database_snapshot(dsn, window_from=window_from, window_to=window_to)
    return reconcile_snapshots(
        database=database,
        broker=broker,
        window_from=window_from,
        window_to=window_to,
    )


def main(repo_root: Path | None = None) -> int:
    root = repo_root or Path(__file__).resolve().parents[2]
    dsn = os.getenv("AUDIT_DATABASE_URL", "")
    if not dsn:
        report = {
            "schema_version": "wolf15.channel-b-reconciliation.v2",
            "AUDIT_DATABASE_URL": "NOT_PRESENT",
            "DATABASE_MIRROR_STATE": "NOT_MEASURED",
            "DIRECT_BROKER_STATE": "NOT_MEASURED",
            "BROKER_RECONCILIATION": "NOT_EXECUTED",
            "B-B16": "NOT_EXECUTED",
            "EXECUTION_READY": False,
            "PRODUCTION_READY": False,
            "error_type": "AUDIT_DATABASE_URL_NOT_PRESENT",
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    try:
        account_binding.decode_secret_key(os.getenv(account_binding.KEY_ENV, ""))
        account_binding.validate_key_id(os.getenv(account_binding.KEY_ID_ENV, ""))
    except account_binding.AccountBindingError as exc:
        report = {
            "schema_version": "wolf15.channel-b-reconciliation.v2",
            "AUDIT_DATABASE_URL": "PRESENT",
            "DATABASE_MIRROR_STATE": "NOT_MEASURED",
            "DIRECT_BROKER_STATE": "NOT_MEASURED",
            "BROKER_RECONCILIATION": "NOT_EXECUTED",
            "B-B16": "NOT_EXECUTED",
            "EXECUTION_READY": False,
            "PRODUCTION_READY": False,
            "error_type": exc.code,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    config_path = Path.home() / ".codex" / "config.toml"
    report = asyncio.run(run_reconciliation(dsn=dsn, repo_root=root, config_path=config_path))
    print(json.dumps(report, default=str, indent=2, sort_keys=True))
    return 0 if report["B-B16"] in {"PASS", "EXECUTED_INCOMPLETE", "EXECUTED_BLOCKED"} else 1


if __name__ == "__main__":
    sys.exit(main())
