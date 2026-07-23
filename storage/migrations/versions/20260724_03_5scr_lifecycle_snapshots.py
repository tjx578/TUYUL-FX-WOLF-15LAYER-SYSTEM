"""Add durable lifecycle anchors, immutable evidence snapshots, and retries.

Revision ID: 20260724_03
Revises: 20260724_02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260724_03"
down_revision = "20260724_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_lifecycles",
        sa.Column("lifecycle_id", sa.Text(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anchor_event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_sequence", sa.BigInteger(), nullable=False),
        sa.Column("latest_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("last_sequence > 0", name="ck_5scr_lifecycle_sequence_positive"),
        sa.CheckConstraint("anchor_sequence > 0", name="ck_5scr_lifecycle_anchor_sequence_positive"),
    )
    op.create_index(
        "ix_5scr_lifecycles_symbol_anchor",
        "strategy_5scr_lifecycles",
        ["symbol", "anchor_at"],
    )
    op.execute(
        """
        INSERT INTO strategy_5scr_lifecycles (
            lifecycle_id, symbol, anchor_at, anchor_event_id, anchor_sequence,
            latest_event_at, last_sequence
        )
        SELECT DISTINCT ON (lifecycle_id)
               lifecycle_id, symbol,
               first_value(signal_valid_at) OVER (
                   PARTITION BY lifecycle_id
                   ORDER BY lifecycle_sequence, signal_valid_at, event_id
               ),
               first_value(event_id) OVER (
                   PARTITION BY lifecycle_id
                   ORDER BY lifecycle_sequence, signal_valid_at, event_id
               ),
               min(lifecycle_sequence) OVER (PARTITION BY lifecycle_id),
               max(signal_valid_at) OVER (PARTITION BY lifecycle_id),
               max(lifecycle_sequence) OVER (PARTITION BY lifecycle_id)
        FROM pressure_outbox
        ORDER BY lifecycle_id, lifecycle_sequence, signal_valid_at, event_id
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "strategy_5scr_evidence_snapshots",
        sa.Column("snapshot_id", sa.String(length=80), primary_key=True),
        sa.Column("lifecycle_id", sa.Text(), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["lifecycle_id"],
            ["strategy_5scr_lifecycles.lifecycle_id"],
            name="fk_5scr_snapshot_lifecycle",
        ),
        sa.UniqueConstraint("event_id", name="uq_5scr_snapshot_event"),
    )
    op.create_index(
        "ix_5scr_snapshots_lifecycle_decision",
        "strategy_5scr_evidence_snapshots",
        ["lifecycle_id", "decision_at"],
    )

    with op.batch_alter_table("strategy_5scr_inbox") as batch:
        batch.add_column(
            sa.Column(
                "evidence_next_attempt_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            )
        )
    op.create_index(
        "ix_5scr_inbox_evidence_retry",
        "strategy_5scr_inbox",
        ["evidence_next_attempt_at", "received_at"],
        postgresql_where=sa.text("status = 'WAITING_EVIDENCE'"),
    )


def downgrade() -> None:
    op.drop_index("ix_5scr_inbox_evidence_retry", table_name="strategy_5scr_inbox")
    with op.batch_alter_table("strategy_5scr_inbox") as batch:
        batch.drop_column("evidence_next_attempt_at")
    op.drop_index(
        "ix_5scr_snapshots_lifecycle_decision",
        table_name="strategy_5scr_evidence_snapshots",
    )
    op.drop_table("strategy_5scr_evidence_snapshots")
    op.drop_index("ix_5scr_lifecycles_symbol_anchor", table_name="strategy_5scr_lifecycles")
    op.drop_table("strategy_5scr_lifecycles")
