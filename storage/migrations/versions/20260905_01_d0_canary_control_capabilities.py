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
    # A pre-V3 DEMO command may only cross this migration when its lifecycle is
    # already terminal.  Never manufacture a packet/hash for historical data,
    # and never infer a terminal outcome from age alone.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM execution_commands
                WHERE source_event = 'ENGINEERING_DEMO_CANARY'
                  AND (
                      state NOT IN (
                          'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                          'SHADOW_COMPLETED','SHADOW_REJECTED'
                      )
                      OR terminal_at IS NULL
                  )
            ) THEN
                RAISE EXCEPTION 'historical ENGINEERING_DEMO_CANARY command is nonterminal or ambiguous'
                    USING ERRCODE='23514',
                          CONSTRAINT='ck_demo_historical_terminal_required';
            END IF;
        END;
        $$;
        """
    )
    op.add_column("execution_commands", sa.Column("authority_packet_sha256", sa.String(length=64), nullable=True))
    op.add_column("execution_commands", sa.Column("command_content_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "execution_commands",
        sa.Column("legacy_authority_exempt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "execution_commands",
        sa.Column("legacy_authority_classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE execution_commands
        SET legacy_authority_exempt = true,
            legacy_authority_classified_at = transaction_timestamp()
        WHERE source_event = 'ENGINEERING_DEMO_CANARY'
        """
    )

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
            OR legacy_authority_exempt
            OR (authority_packet_sha256 IS NOT NULL AND command_content_sha256 IS NOT NULL)
        )
        AND (
            NOT legacy_authority_exempt
            OR (
                source_event = 'ENGINEERING_DEMO_CANARY'
                AND authority_packet_sha256 IS NULL
                AND command_content_sha256 IS NULL
                AND state IN (
                    'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                    'SHADOW_COMPLETED','SHADOW_REJECTED'
                )
                AND terminal_at IS NOT NULL
            )
        )
        AND (legacy_authority_exempt = (legacy_authority_classified_at IS NOT NULL))
        """,
    )
    op.execute(
        """
        CREATE FUNCTION guard_execution_command_legacy_authority() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.legacy_authority_exempt THEN
                    RAISE EXCEPTION 'historical authority-exempt command is immutable'
                        USING ERRCODE='23514',
                              CONSTRAINT='ck_demo_legacy_command_immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT' AND NEW.legacy_authority_exempt THEN
                RAISE EXCEPTION 'new command cannot claim historical authority exemption'
                    USING ERRCODE='23514',
                          CONSTRAINT='ck_demo_legacy_authority_insert_forbidden';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.legacy_authority_exempt THEN
                RAISE EXCEPTION 'historical authority-exempt command is immutable'
                    USING ERRCODE='23514',
                          CONSTRAINT='ck_demo_legacy_command_immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                NEW.legacy_authority_exempt IS DISTINCT FROM OLD.legacy_authority_exempt
                OR NEW.legacy_authority_classified_at IS DISTINCT FROM OLD.legacy_authority_classified_at
            ) THEN
                RAISE EXCEPTION 'historical authority classification is migration-owned'
                    USING ERRCODE='23514',
                          CONSTRAINT='ck_demo_legacy_classification_immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_execution_command_legacy_authority
        BEFORE INSERT OR UPDATE OR DELETE ON execution_commands
        FOR EACH ROW EXECUTE FUNCTION guard_execution_command_legacy_authority();
        """
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
    op.execute("DROP TRIGGER IF EXISTS trg_execution_command_legacy_authority ON execution_commands")
    op.execute("DROP FUNCTION IF EXISTS guard_execution_command_legacy_authority()")
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
    op.drop_column("execution_commands", "legacy_authority_classified_at")
    op.drop_column("execution_commands", "legacy_authority_exempt")
    op.drop_column("execution_commands", "command_content_sha256")
    op.drop_column("execution_commands", "authority_packet_sha256")
