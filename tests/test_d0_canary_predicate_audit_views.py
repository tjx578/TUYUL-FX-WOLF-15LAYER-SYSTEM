"""Static contract for the two D0 canary predicate audit views (PostgreSQL ACLs have a separate test)."""

import re
from importlib import import_module
from pathlib import Path

migration = import_module("storage.migrations.versions.20260919_01_d0_canary_predicate_audit_views")


def _columns(sql: str) -> list[str]:
    select = sql.split("FROM public.", 1)[0]
    return re.findall(r"(?:AS\s+|\bs\.|\br\.)(\w+)\s*(?:,|\n\s*FROM|$)", select)


def test_revision_chain():
    assert migration.revision == "20260919_01"
    assert migration.down_revision == "20260915_02"


def test_symbol_capability_view_exposes_only_gate_fields_for_exact_snapshot():
    sql = migration.SYMBOL_CAPABILITY_SQL
    for column in (
        "executor_id",
        "snapshot_id",
        "account_matches_executor",
        "captured_at",
        "trade_allowed",
        "autotrading_enabled",
        "margin_mode",
        "canonical_symbol",
        "broker_symbol",
        "digits",
        "point",
        "tick_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "stops_level_points",
        "freeze_level_points",
    ):
        assert re.search(rf"\b{column}\b", sql), column
    # Keyed by exact stored snapshot rows; no "latest" selection or ordering inside the view.
    assert "ORDER BY" not in sql.upper() and "LIMIT" not in sql.upper() and "max(" not in sql.lower()
    for forbidden in ("balance", "equity", "login_hash", "open_positions", "pending_orders", "s.payload AS"):
        assert forbidden not in sql


def test_receipt_view_exposes_predicate_inputs_without_payload_or_tickets():
    sql = migration.RECONCILIATION_RECEIPT_SQL
    for column in (
        "reconciliation_id",
        "executor_id",
        "source_snapshot_id",
        "source_snapshot_sha256",
        "observed_at",
        "broker_ledger_reconciled",
        "terminal_reason",
        "positions_count",
        "pending_orders_count",
        "orphan_wolf15_count",
        "unattributed_count",
        "ambiguous_count",
        "ledger_mismatch_count",
        "account_reference",
        "broker_server_sha256",
        "receipt_sha256",
        "source_snapshot_exists",
    ):
        assert re.search(rf"\b{column}\b", sql), column
    assert "r.payload" not in sql and "r.counts," not in sql
    for forbidden in ("ticket", "position_id", "login"):
        assert forbidden not in sql.lower()


def test_auditor_receives_select_on_views_only():
    source = Path(str(migration.__file__)).read_text(encoding="utf-8")
    grants = re.findall(r"GRANT\s+(\w+)\s+ON\s+([\w.]+)", source)
    assert set(grants) == {
        ("USAGE", "SCHEMA"),
        ("SELECT", "wolf15_audit.executor_snapshot_symbol_capability_v1"),
        ("SELECT", "wolf15_audit.direct_reconciliation_receipt_v1"),
    }
    assert "security_barrier=true" in source
    assert "REVOKE ALL ON wolf15_audit.{name} FROM PUBLIC" in source
