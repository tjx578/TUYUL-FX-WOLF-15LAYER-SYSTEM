"""Add the durable Strategy 5S-CR pressure outbox and idempotent inbox.

Revision ID: 20260720_01
Revises: 20260719_01

``pressure_outbox`` is intentionally not an execution-command outbox.  The
event remains non-executable and is consumed only by Strategy 5S-CR analysis.
Because the current pressure emitter has no separate durable state table, the
outbox row itself is the durable pressure record.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260720_01"
down_revision = "20260719_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("pressure_lifecycle_sequences"):
        op.create_table(
            "pressure_lifecycle_sequences",
            sa.Column("lifecycle_id", sa.Text(), primary_key=True),
            sa.Column("last_sequence", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("last_sequence >= 0", name="ck_pressure_lifecycle_sequence_nonnegative"),
        )

    if not inspector.has_table("pressure_outbox"):
        op.create_table(
            "pressure_outbox",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column("event_id", sa.UUID(as_uuid=True), nullable=False, unique=True),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("schema_version", sa.String(100), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("lifecycle_id", sa.Text(), nullable=False),
            sa.Column("lifecycle_sequence", sa.BigInteger(), nullable=False),
            sa.Column("source_clean_block_id", sa.Text(), nullable=True),
            sa.Column("source_watch_id", sa.Text(), nullable=True),
            sa.Column("signal_valid_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_by", sa.String(200), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint(
                "status IN ('PENDING', 'IN_FLIGHT', 'PUBLISHED', 'DEAD')",
                name="ck_pressure_outbox_status",
            ),
            sa.CheckConstraint("attempt_count >= 0", name="ck_pressure_outbox_attempt_count"),
            sa.CheckConstraint("lifecycle_sequence > 0", name="ck_pressure_outbox_sequence_positive"),
            sa.CheckConstraint(
                "source_clean_block_id IS NOT NULL OR source_watch_id IS NOT NULL",
                name="ck_pressure_outbox_canonical_lineage",
            ),
            sa.UniqueConstraint(
                "lifecycle_id",
                "lifecycle_sequence",
                name="uq_pressure_outbox_lifecycle_sequence",
            ),
        )
        op.create_index(
            "ix_pressure_outbox_dispatch",
            "pressure_outbox",
            ["status", "available_at", "lease_expires_at", "created_at"],
        )
        op.create_index(
            "ix_pressure_outbox_lifecycle",
            "pressure_outbox",
            ["lifecycle_id", "lifecycle_sequence"],
        )
        op.create_index("ix_pressure_outbox_signal_valid_at", "pressure_outbox", ["signal_valid_at"])

    if not inspector.has_table("strategy_5scr_inbox"):
        op.create_table(
            "strategy_5scr_inbox",
            sa.Column("event_id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result_id", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'RECEIVED'")),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('RECEIVED', 'PROCESSING', 'WAITING_EVIDENCE', 'PROCESSED', "
                "'INTEGRITY_VIOLATION', 'FAILED')",
                name="ck_strategy_5scr_inbox_status",
            ),
        )
        op.create_index("ix_strategy_5scr_inbox_status_received", "strategy_5scr_inbox", ["status", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_strategy_5scr_inbox_status_received", table_name="strategy_5scr_inbox")
    op.drop_table("strategy_5scr_inbox")
    op.drop_index("ix_pressure_outbox_signal_valid_at", table_name="pressure_outbox")
    op.drop_index("ix_pressure_outbox_lifecycle", table_name="pressure_outbox")
    op.drop_index("ix_pressure_outbox_dispatch", table_name="pressure_outbox")
    op.drop_table("pressure_outbox")
    op.drop_table("pressure_lifecycle_sequences")
