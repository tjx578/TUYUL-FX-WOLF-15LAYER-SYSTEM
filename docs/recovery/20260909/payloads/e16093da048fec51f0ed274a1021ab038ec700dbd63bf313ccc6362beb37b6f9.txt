"""Add immutable D0 canary authority, mode-transition, and broker-truth ledgers.

Revision ID: 20260905_01
Revises: 20260823_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260905_01"
down_revision = "20260823_01"
branch_labels = None
depends_on = None


def _immutable(table: str) -> None:
    function = f"reject_{table}_mutation"
    trigger = f"trg_{table}_immutable"
    op.execute(
        f"""
        CREATE FUNCTION {function}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable D0 canary control evidence'
                USING ERRCODE='23514', CONSTRAINT='ck_d0_canary_control_immutable';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER {trigger}
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {function}();
        """
    )


def upgrade() -> None:
    op.add_column("execution_commands", sa.Column("authority_packet_sha256", sa.String(length=64), nullable=True))
    op.add_column("execution_commands", sa.Column("command_content_sha256", sa.String(length=64), nullable=True))

    op.create_table(
        "engineering_demo_canary_authority_packets",
        sa.Column("authority_packet_id", sa.String(length=96), primary_key=True),
        sa.Column("authority_packet_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("command_id", sa.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("command_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=200), nullable=False, unique=True),
        sa.Column("approved_by", sa.String(length=160), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issuer_source_revision", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("authority_packet_sha256 ~ '^[0-9a-f]{64}$'", name="ck_demo_packet_sha256"),
        sa.CheckConstraint("command_content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_demo_content_sha256"),
        sa.CheckConstraint("expires_at > approved_at", name="ck_demo_packet_window"),
    )
    op.create_foreign_key(
        "fk_demo_command_authority_packet",
        "execution_commands",
        "engineering_demo_canary_authority_packets",
        ["authority_packet_sha256"],
        ["authority_packet_sha256"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_demo_command_frozen_authority_pair",
        "execution_commands",
        """
        (authority_packet_sha256 IS NULL) = (command_content_sha256 IS NULL)
        AND (
            source_event <> 'ENGINEERING_DEMO_CANARY'
            OR (authority_packet_sha256 IS NOT NULL AND command_content_sha256 IS NOT NULL)
        )
        """,
    )

    op.create_table(
        "direct_broker_reconciliation_receipts",
        sa.Column("reconciliation_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("executor_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("account_reference", sa.String(length=71), nullable=False),
        sa.Column("broker_server_sha256", sa.String(length=71), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("source_snapshot_sha256", sa.String(length=71), nullable=False),
        sa.Column("command_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counts", JSONB(), nullable=False),
        sa.Column("broker_ledger_reconciled", sa.Boolean(), nullable=False),
        sa.Column("terminal_reason", sa.String(length=100), nullable=False),
        sa.Column("receipt_sha256", sa.String(length=71), nullable=False, unique=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("account_reference ~ '^sha256:[0-9a-f]{64}$'", name="ck_direct_recon_account_hash"),
        sa.CheckConstraint("broker_server_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_direct_recon_server_hash"),
        sa.CheckConstraint("source_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_direct_recon_snapshot_hash"),
        sa.CheckConstraint("receipt_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_direct_recon_receipt_hash"),
    )
    op.create_index(
        "ix_direct_recon_executor_observed",
        "direct_broker_reconciliation_receipts",
        ["executor_id", "observed_at"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_direct_recon_snapshot_command
        ON direct_broker_reconciliation_receipts (
            source_snapshot_sha256,
            COALESCE(command_id, '00000000-0000-0000-0000-000000000000'::uuid)
        )
        """
    )

    op.create_table(
        "executor_mode_transition_authority_packets",
        sa.Column("authority_packet_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("authority_packet_sha256", sa.String(length=71), nullable=False, unique=True),
        sa.Column("approval_id", sa.String(length=200), nullable=False, unique=True),
        sa.Column("executor_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_mode", sa.String(length=16), nullable=False),
        sa.Column("new_mode", sa.String(length=16), nullable=False),
        sa.Column("account_reference", sa.String(length=200), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column("configuration_sha256", sa.String(length=71), nullable=False),
        sa.Column("final_shadow_receipt_sha256", sa.String(length=71), nullable=False),
        sa.Column("approved_by", sa.String(length=200), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(previous_mode='SHADOW' AND new_mode='DEMO') OR (previous_mode='DEMO' AND new_mode='SHADOW')",
            name="ck_mode_authority_direction",
        ),
        sa.CheckConstraint("expires_at > approved_at", name="ck_mode_authority_window"),
    )
    op.create_table(
        "executor_mode_transition_receipts",
        sa.Column("transition_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "authority_packet_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("executor_mode_transition_authority_packets.authority_packet_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("executor_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_mode", sa.String(length=16), nullable=False),
        sa.Column("new_mode", sa.String(length=16), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("transition_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("new_version = previous_version + 1", name="ck_mode_transition_version_step"),
        sa.CheckConstraint("transition_status='APPLIED'", name="ck_mode_transition_applied"),
    )

    for table in (
        "engineering_demo_canary_authority_packets",
        "direct_broker_reconciliation_receipts",
        "executor_mode_transition_authority_packets",
        "executor_mode_transition_receipts",
    ):
        _immutable(table)


def downgrade() -> None:
    for table in (
        "executor_mode_transition_receipts",
        "executor_mode_transition_authority_packets",
        "direct_broker_reconciliation_receipts",
        "engineering_demo_canary_authority_packets",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()")

    op.drop_table("executor_mode_transition_receipts")
    op.drop_table("executor_mode_transition_authority_packets")
    op.drop_index("ix_direct_recon_executor_observed", table_name="direct_broker_reconciliation_receipts")
    op.execute("DROP INDEX IF EXISTS uq_direct_recon_snapshot_command")
    op.drop_table("direct_broker_reconciliation_receipts")
    op.drop_constraint("ck_demo_command_frozen_authority_pair", "execution_commands", type_="check")
    op.drop_constraint("fk_demo_command_authority_packet", "execution_commands", type_="foreignkey")
    op.drop_table("engineering_demo_canary_authority_packets")
    op.drop_column("execution_commands", "command_content_sha256")
    op.drop_column("execution_commands", "authority_packet_sha256")
