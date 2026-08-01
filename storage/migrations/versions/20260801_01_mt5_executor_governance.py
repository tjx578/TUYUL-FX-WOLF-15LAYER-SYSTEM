"""Add fail-closed governance for the MT5 executor bridge.

Revision ID: 20260801_01
Revises: 20260729_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260801_01"
down_revision = "20260729_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executor_instances",
        sa.Column("mode_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "executor_instances",
        sa.Column("mode_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "executor_instances",
        sa.Column("mode_changed_by", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "executor_instances",
        sa.Column("mode_change_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_executor_mode_version_positive",
        "executor_instances",
        "mode_version > 0",
    )

    op.create_table(
        "executor_bridge_governance",
        sa.Column("singleton_id", sa.SmallInteger(), primary_key=True),
        sa.Column("kill_switch_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "kill_switch_reason",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'DEFAULT_ENGAGED'"),
        ),
        sa.Column("governance_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "updated_by",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("'MIGRATION'"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("singleton_id = 1", name="ck_executor_governance_singleton"),
        sa.CheckConstraint("governance_version > 0", name="ck_executor_governance_version_positive"),
        sa.CheckConstraint(
            "length(btrim(kill_switch_reason)) > 0",
            name="ck_executor_governance_reason_not_blank",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO executor_bridge_governance (singleton_id)
            VALUES (1)
            ON CONFLICT (singleton_id) DO NOTHING
            """
        )
    )

    op.create_table(
        "executor_governance_audit",
        sa.Column(
            "audit_id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Deliberately not an FK: an immutable audit must retain the executor
        # identity even after the operational agent row is removed.
        sa.Column("executor_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_state", JSONB(), nullable=False),
        sa.Column("new_state", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(btrim(action)) > 0", name="ck_executor_governance_audit_action"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="ck_executor_governance_audit_actor"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_executor_governance_audit_reason"),
    )
    op.create_index(
        "ix_executor_governance_audit_created",
        "executor_governance_audit",
        ["created_at"],
    )
    op.create_index(
        "ix_executor_governance_audit_executor_created",
        "executor_governance_audit",
        ["executor_id", "created_at"],
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_executor_governance_audit_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'executor_governance_audit is append-only'
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_executor_governance_audit_immutable
            BEFORE UPDATE OR DELETE ON executor_governance_audit
            FOR EACH ROW EXECUTE FUNCTION reject_executor_governance_audit_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_executor_governance_audit_immutable ON executor_governance_audit")
    op.execute("DROP FUNCTION IF EXISTS reject_executor_governance_audit_mutation()")
    op.drop_index("ix_executor_governance_audit_executor_created", table_name="executor_governance_audit")
    op.drop_index("ix_executor_governance_audit_created", table_name="executor_governance_audit")
    op.drop_table("executor_governance_audit")
    op.drop_table("executor_bridge_governance")
    op.drop_constraint("ck_executor_mode_version_positive", "executor_instances", type_="check")
    op.drop_column("executor_instances", "mode_change_reason")
    op.drop_column("executor_instances", "mode_changed_by")
    op.drop_column("executor_instances", "mode_changed_at")
    op.drop_column("executor_instances", "mode_version")
