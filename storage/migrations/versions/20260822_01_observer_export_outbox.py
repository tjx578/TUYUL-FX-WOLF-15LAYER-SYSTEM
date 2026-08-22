"""Add the append-only Wolf15 observer telemetry export.

Revision ID: 20260822_01
Revises: 20260813_02

The consumer cursor deliberately does not live here.  Wolf15 owns immutable
export facts and their stream heads; the observer owns consumption progress in
its own database and receives SELECT-only access to this schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260822_01"
down_revision = "20260813_02"
branch_labels = None
depends_on = None

SCHEMA = "observer_export"
STREAM_HEADS = "stream_heads"
OUTBOX = "outbox"
OBSERVER_READER_ROLE = "wolf15_observer_reader"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")

    op.create_table(
        STREAM_HEADS,
        sa.Column("stream_id", sa.Text(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_event_hash", sa.String(length=71), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("stream_id", name="pk_observer_export_stream_heads"),
        sa.CheckConstraint(
            "last_sequence >= 0 AND "
            "((last_sequence = 0 AND last_event_hash IS NULL) OR "
            " (last_sequence > 0 AND last_event_hash ~ '^sha256:[0-9a-f]{64}$'))",
            name="ck_observer_export_stream_head_shape",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        OUTBOX,
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("logical_event_key", sa.Text(), nullable=False),
        sa.Column("stream_id", sa.Text(), nullable=False),
        sa.Column("stream_sequence", sa.BigInteger(), nullable=False),
        sa.Column("previous_stream_sequence", sa.BigInteger(), nullable=True),
        sa.Column("previous_event_hash", sa.String(length=71), nullable=True),
        sa.Column("event_hash", sa.String(length=71), nullable=False),
        sa.Column("authority_class", sa.String(length=64), nullable=False),
        sa.Column("payload_type", sa.String(length=160), nullable=False),
        sa.Column("payload_version", sa.String(length=100), nullable=False),
        sa.Column("envelope_version", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=71), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("source_service", sa.String(length=160), nullable=False),
        sa.Column("source_commit_sha", sa.String(length=64), nullable=False),
        sa.Column("source_deployment_id", sa.String(length=200), nullable=True),
        sa.Column("policy_version", sa.String(length=160), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("event_id", name="pk_observer_export_outbox"),
        sa.UniqueConstraint(
            "payload_type",
            "logical_event_key",
            name="uq_observer_export_logical_event",
        ),
        sa.UniqueConstraint(
            "stream_id",
            "stream_sequence",
            name="uq_observer_export_stream_sequence",
        ),
        sa.UniqueConstraint(
            "stream_id",
            "stream_sequence",
            "event_hash",
            name="uq_observer_export_stream_chain_target",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "previous_stream_sequence", "previous_event_hash"],
            [
                f"{SCHEMA}.{OUTBOX}.stream_id",
                f"{SCHEMA}.{OUTBOX}.stream_sequence",
                f"{SCHEMA}.{OUTBOX}.event_hash",
            ],
            name="fk_observer_export_immediate_predecessor",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("stream_sequence > 0", name="ck_observer_export_sequence_positive"),
        sa.CheckConstraint(
            "(stream_sequence = 1 AND previous_stream_sequence IS NULL AND previous_event_hash IS NULL) OR "
            "(stream_sequence > 1 AND previous_stream_sequence = stream_sequence - 1 "
            " AND previous_event_hash ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_observer_export_predecessor_shape",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^sha256:[0-9a-f]{64}$' AND event_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_observer_export_hash_shape",
        ),
        sa.CheckConstraint(
            "source_system = 'WOLF15' AND envelope #>> '{source,system}' = 'WOLF15'",
            name="ck_observer_export_source_system",
        ),
        sa.CheckConstraint(
            "envelope #>> '{authority,observer_authority}' = 'OBSERVATIONAL_ONLY' AND "
            "(envelope #>> '{safety,observer_can_mutate_source}')::boolean IS FALSE",
            name="ck_observer_export_observational_only",
        ),
        sa.CheckConstraint(
            "envelope #>> '{stream,stream_id}' = stream_id AND "
            "(envelope #>> '{stream,stream_sequence}')::bigint = stream_sequence AND "
            "envelope #>> '{payload,payload_hash}' = payload_hash AND "
            "envelope #>> '{payload,payload_type}' = payload_type AND "
            "envelope #>> '{payload,payload_version}' = payload_version AND "
            "envelope #>> '{source,schema_version}' = envelope_version",
            name="ck_observer_export_envelope_projection",
        ),
        sa.CheckConstraint("published_at >= occurred_at", name="ck_observer_export_time_order"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_observer_export_outbox_stream_read",
        OUTBOX,
        ["stream_id", "stream_sequence"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_observer_export_outbox_published",
        OUTBOX,
        ["published_at", "event_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_observer_export_outbox_payload_type",
        OUTBOX,
        ["payload_type", "published_at"],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_outbox_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'observer export outbox is append-only'
                USING ERRCODE='23514', CONSTRAINT='ck_observer_export_append_only';
        END $$;

        CREATE TRIGGER trg_observer_export_reject_row_mutation
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{OUTBOX}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_outbox_mutation();

        CREATE TRIGGER trg_observer_export_reject_truncate
        BEFORE TRUNCATE ON {SCHEMA}.{OUTBOX}
        FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_outbox_mutation();
        """
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(
        f"""
        DO $observer_grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{OBSERVER_READER_ROLE}') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA {SCHEMA} TO {OBSERVER_READER_ROLE}';
                EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {OBSERVER_READER_ROLE}';
                EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} '
                        'GRANT SELECT ON TABLES TO {OBSERVER_READER_ROLE}';
            END IF;
        END
        $observer_grant$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_observer_export_reject_truncate ON {SCHEMA}.{OUTBOX}")
    op.execute(f"DROP TRIGGER IF EXISTS trg_observer_export_reject_row_mutation ON {SCHEMA}.{OUTBOX}")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_outbox_mutation()")
    op.drop_index("ix_observer_export_outbox_payload_type", table_name=OUTBOX, schema=SCHEMA)
    op.drop_index("ix_observer_export_outbox_published", table_name=OUTBOX, schema=SCHEMA)
    op.drop_index("ix_observer_export_outbox_stream_read", table_name=OUTBOX, schema=SCHEMA)
    op.drop_table(OUTBOX, schema=SCHEMA)
    op.drop_table(STREAM_HEADS, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
