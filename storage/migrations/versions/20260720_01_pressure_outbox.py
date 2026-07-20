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
from sqlalchemy.engine.reflection import Inspector

revision = "20260720_01"
down_revision = "20260719_01"
branch_labels = None
depends_on = None


def _index_names(inspector: Inspector, table_name: str) -> set[str]:
    return {str(item["name"]) for item in inspector.get_indexes(table_name)}


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

    inspector = inspect(bind)
    pressure_indexes = _index_names(inspector, "pressure_outbox")
    if "ix_pressure_outbox_pending" not in pressure_indexes:
        op.create_index(
            "ix_pressure_outbox_pending",
            "pressure_outbox",
            ["available_at", "created_at"],
            postgresql_where=sa.text("status = 'PENDING'"),
        )
    if "ix_pressure_outbox_lease_expiry" not in pressure_indexes:
        op.create_index(
            "ix_pressure_outbox_lease_expiry",
            "pressure_outbox",
            ["lease_expires_at", "created_at"],
            postgresql_where=sa.text("status = 'IN_FLIGHT'"),
        )
    if "ix_pressure_outbox_published" not in pressure_indexes:
        op.create_index(
            "ix_pressure_outbox_published",
            "pressure_outbox",
            ["published_at", "created_at"],
            postgresql_where=sa.text("status = 'PUBLISHED'"),
        )
    if "ix_pressure_outbox_lifecycle" not in pressure_indexes:
        op.create_index(
            "ix_pressure_outbox_lifecycle",
            "pressure_outbox",
            ["lifecycle_id", "lifecycle_sequence"],
        )
    if "ix_pressure_outbox_signal_valid_at" not in pressure_indexes:
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

    inspector = inspect(bind)
    inbox_indexes = _index_names(inspector, "strategy_5scr_inbox")
    if "ix_strategy_5scr_inbox_status_received" not in inbox_indexes:
        op.create_index("ix_strategy_5scr_inbox_status_received", "strategy_5scr_inbox", ["status", "received_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("strategy_5scr_inbox"):
        inbox_indexes = _index_names(inspector, "strategy_5scr_inbox")
        if "ix_strategy_5scr_inbox_status_received" in inbox_indexes:
            op.drop_index("ix_strategy_5scr_inbox_status_received", table_name="strategy_5scr_inbox")
        op.drop_table("strategy_5scr_inbox")

    inspector = inspect(bind)
    if inspector.has_table("pressure_outbox"):
        pressure_indexes = _index_names(inspector, "pressure_outbox")
        for index_name in (
            "ix_pressure_outbox_signal_valid_at",
            "ix_pressure_outbox_lifecycle",
            "ix_pressure_outbox_published",
            "ix_pressure_outbox_lease_expiry",
            "ix_pressure_outbox_pending",
        ):
            if index_name in pressure_indexes:
                op.drop_index(index_name, table_name="pressure_outbox")
        op.drop_table("pressure_outbox")

    inspector = inspect(bind)
    if inspector.has_table("pressure_lifecycle_sequences"):
        op.drop_table("pressure_lifecycle_sequences")
