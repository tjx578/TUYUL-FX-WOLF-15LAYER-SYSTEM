"""Add durable MT5 dumb-executor bridge ledger.

Revision ID: 20260719_01
Revises: 20260520_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260719_01"
down_revision = "20260520_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("executor_instances"):
        op.create_table(
            "executor_instances",
            sa.Column(
                "executor_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_agents.id", ondelete="RESTRICT"),
                primary_key=True,
            ),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("login_hash", sa.String(80), nullable=False),
            sa.Column("broker_server", sa.String(200), nullable=False),
            sa.Column("terminal_build", sa.Integer(), nullable=False),
            sa.Column("ea_version", sa.String(50), nullable=False),
            sa.Column("protocol_version", sa.String(50), nullable=False),
            sa.Column("execution_mode", sa.String(16), nullable=False, server_default=sa.text("'SHADOW'")),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'REGISTERED'")),
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("execution_mode IN ('SHADOW', 'DEMO', 'LIVE')", name="ck_executor_execution_mode"),
            sa.UniqueConstraint("account_id", "login_hash", "broker_server", name="uq_executor_account_binding"),
        )
        op.create_index("ix_executor_instances_heartbeat", "executor_instances", ["last_heartbeat_at"])

    if not inspector.has_table("executor_account_snapshots"):
        op.create_table(
            "executor_account_snapshots",
            sa.Column("snapshot_id", sa.String(200), primary_key=True),
            sa.Column(
                "executor_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("executor_instances.executor_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("balance", sa.Numeric(24, 8), nullable=False),
            sa.Column("equity", sa.Numeric(24, 8), nullable=False),
            sa.Column("floating_pnl", sa.Numeric(24, 8), nullable=False),
            sa.Column("used_margin", sa.Numeric(24, 8), nullable=False),
            sa.Column("free_margin", sa.Numeric(24, 8), nullable=False),
            sa.Column("margin_level_pct", sa.Numeric(24, 8), nullable=True),
            sa.Column("margin_mode", sa.String(16), nullable=False),
            sa.Column("trade_allowed", sa.Boolean(), nullable=False),
            sa.Column("autotrading_enabled", sa.Boolean(), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("margin_mode IN ('HEDGING', 'NETTING')", name="ck_executor_snapshot_margin_mode"),
        )
        op.create_index(
            "ix_executor_snapshots_executor_captured",
            "executor_account_snapshots",
            ["executor_id", "captured_at"],
        )

    if not inspector.has_table("execution_commands"):
        op.create_table(
            "execution_commands",
            sa.Column("command_id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "executor_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("executor_instances.executor_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("source_signal_id", sa.String(200), nullable=False),
            sa.Column("source_signal_hash", sa.String(80), nullable=False),
            sa.Column("idempotency_key", sa.String(250), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("payload_hash", sa.String(80), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("claim_token_hash", sa.String(64), nullable=True),
            sa.Column("claimed_by", sa.UUID(as_uuid=True), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_report_sequence", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("expires_at > issued_at", name="ck_execution_command_expiry"),
            sa.CheckConstraint(
                "not_before >= issued_at AND not_before < expires_at", name="ck_execution_command_window"
            ),
            sa.UniqueConstraint("account_id", "idempotency_key", name="uq_execution_command_idempotency"),
        )
        op.create_index(
            "ix_execution_commands_poll",
            "execution_commands",
            ["executor_id", "state", "not_before", "expires_at"],
        )
        op.create_index("ix_execution_commands_signal", "execution_commands", ["source_signal_id"])

    if not inspector.has_table("execution_reports"):
        op.create_table(
            "execution_reports",
            sa.Column("report_id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "command_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("execution_commands.command_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("executor_id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(64), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("payload_hash", sa.String(80), nullable=False),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("command_id", "sequence", name="uq_execution_report_sequence"),
        )
        op.create_index(
            "ix_execution_reports_command_received",
            "execution_reports",
            ["command_id", "received_at"],
        )

    if not inspector.has_table("broker_entities"):
        op.create_table(
            "broker_entities",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column(
                "command_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("execution_commands.command_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("entity_type", sa.String(16), nullable=False),
            sa.Column("broker_ticket", sa.BigInteger(), nullable=False),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("entity_type IN ('ORDER', 'DEAL', 'POSITION')", name="ck_broker_entity_type"),
            sa.UniqueConstraint("command_id", "entity_type", "broker_ticket", name="uq_broker_entity_mapping"),
        )


def downgrade() -> None:
    op.drop_table("broker_entities")
    op.drop_index("ix_execution_reports_command_received", table_name="execution_reports")
    op.drop_table("execution_reports")
    op.drop_index("ix_execution_commands_signal", table_name="execution_commands")
    op.drop_index("ix_execution_commands_poll", table_name="execution_commands")
    op.drop_table("execution_commands")
    op.drop_index("ix_executor_snapshots_executor_captured", table_name="executor_account_snapshots")
    op.drop_table("executor_account_snapshots")
    op.drop_index("ix_executor_instances_heartbeat", table_name="executor_instances")
    op.drop_table("executor_instances")
