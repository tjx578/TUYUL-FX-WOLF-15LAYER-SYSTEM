"""Expose the two D0 canary predicates the read-only auditor could not measure.

1. wolf15_audit.executor_snapshot_symbol_capability_v1
   Per stored executor account snapshot S, only the SymbolCapability fields the canary gates use
   (exact minimum volume, latest-state veto capability comparison) plus S-level trading flags.
   Looked up by exact snapshot_id; never substitutes a newer snapshot.
2. wolf15_audit.direct_reconciliation_receipt_v1
   Per authoritative direct broker reconciliation receipt, only the enqueue predicate inputs:
   the source snapshot S it covers, its observation time, derived reconciliation flag, terminal reason,
   counts and non-secret digests. No payload, no tickets, no plaintext account identifiers.

Both views are security_barrier projections; the auditor receives SELECT on the views only and never on
the base tables.

Revision ID: 20260919_01
Revises: 20260915_02
"""

from alembic import op

revision = "20260919_01"
down_revision = "20260915_02"
branch_labels = None
depends_on = None

SYMBOL_CAPABILITY_SQL = """
    SELECT s.executor_id,
           s.snapshot_id,
           s.account_id = e.account_id AS account_matches_executor,
           s.captured_at,
           s.trade_allowed,
           s.autotrading_enabled,
           s.margin_mode,
           symbol->>'canonical_symbol' AS canonical_symbol,
           symbol->>'broker_symbol' AS broker_symbol,
           (symbol->>'digits')::integer AS digits,
           (symbol->>'point')::double precision AS point,
           (symbol->>'tick_size')::double precision AS tick_size,
           (symbol->>'volume_min')::double precision AS volume_min,
           (symbol->>'volume_max')::double precision AS volume_max,
           (symbol->>'volume_step')::double precision AS volume_step,
           (symbol->>'stops_level_points')::integer AS stops_level_points,
           (symbol->>'freeze_level_points')::integer AS freeze_level_points
      FROM public.executor_account_snapshots s
      JOIN public.executor_instances e ON e.executor_id = s.executor_id
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.payload->'symbols', '[]'::jsonb)) AS symbol
"""

RECONCILIATION_RECEIPT_SQL = """
    SELECT r.reconciliation_id,
           r.executor_id,
           r.source_snapshot_id,
           r.source_snapshot_sha256,
           r.command_id,
           r.observed_at,
           r.broker_ledger_reconciled,
           r.terminal_reason,
           (r.counts->>'positions')::integer AS positions_count,
           (r.counts->>'pending_orders')::integer AS pending_orders_count,
           (r.counts->>'orphan_wolf15')::integer AS orphan_wolf15_count,
           (r.counts->>'unattributed')::integer AS unattributed_count,
           (r.counts->>'ambiguous')::integer AS ambiguous_count,
           (r.counts->>'ledger_mismatch')::integer AS ledger_mismatch_count,
           r.account_reference,
           r.broker_server_sha256,
           r.receipt_sha256,
           EXISTS (
               SELECT 1
                 FROM public.executor_account_snapshots s
                WHERE s.executor_id = r.executor_id AND s.snapshot_id = r.source_snapshot_id
           ) AS source_snapshot_exists,
           r.created_at
      FROM public.direct_broker_reconciliation_receipts r
"""

VIEWS = {
    "executor_snapshot_symbol_capability_v1": SYMBOL_CAPABILITY_SQL,
    "direct_reconciliation_receipt_v1": RECONCILIATION_RECEIPT_SQL,
}


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS wolf15_audit")
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW wolf15_audit.{name} WITH (security_barrier=true) AS {sql}")
        op.execute(f"REVOKE ALL ON wolf15_audit.{name} FROM PUBLIC")
    op.execute(
        """
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wolf15_auditor') THEN
                GRANT USAGE ON SCHEMA wolf15_audit TO wolf15_auditor;
                GRANT SELECT ON wolf15_audit.executor_snapshot_symbol_capability_v1 TO wolf15_auditor;
                GRANT SELECT ON wolf15_audit.direct_reconciliation_receipt_v1 TO wolf15_auditor;
            END IF;
        END $grant$;
        """
    )


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW wolf15_audit.{name}")
