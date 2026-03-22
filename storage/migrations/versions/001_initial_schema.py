"""Initial PostgreSQL schema for persistent backup."""

from __future__ import annotations

from alembic import op
from sqlalchemy import TIMESTAMP, BigInteger, Column, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_snapshots",
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("snapshot_type", String(50), nullable=False),
        Column("account_id", String(100), nullable=False),
        Column("state_data", JSONB, nullable=False),
        Column("created_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
    )
    op.create_index(
        "ix_risk_snapshots_type_account_created",
        "risk_snapshots",
        ["snapshot_type", "account_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "trade_history",
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("trade_id", String(100), nullable=False, unique=True),
        Column("signal_id", String(100), nullable=False),
        Column("account_id", String(100), nullable=False),
        Column("pair", String(20), nullable=False),
        Column("direction", String(10), nullable=False),
        Column("status", String(30), nullable=False),
        Column("risk_mode", String(20), nullable=False),
        Column("total_risk_percent", Float, nullable=False),
        Column("total_risk_amount", Float, nullable=False),
        Column("pnl", Float, nullable=True),
        Column("close_reason", String(50), nullable=True),
        Column("legs", JSONB, nullable=True),
        Column("metadata", JSONB, nullable=True),
        Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now()),
        Column("closed_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_trade_history_account_pair", "trade_history", ["account_id", "pair"])
    op.create_index("ix_trade_history_status", "trade_history", ["status"])
    op.create_index("ix_trade_history_created", "trade_history", ["created_at"])

    op.create_table(
        "accounts",
        Column("account_id", String(100), primary_key=True),
        Column("broker", String(100), nullable=False),
        Column("balance", Float, nullable=False),
        Column("equity", Float, nullable=False),
        Column("currency", String(10), nullable=False, server_default="USD"),
        Column("metadata", JSONB, nullable=True),
        Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now()),
    )

    op.create_table(
        "risk_profiles",
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("account_id", String(100), ForeignKey("accounts.account_id"), nullable=False, unique=True),
        Column("risk_per_trade", Float, nullable=False),
        Column("max_daily_dd", Float, nullable=False),
        Column("max_total_dd", Float, nullable=False),
        Column("max_open_trades", Integer, nullable=False),
        Column("risk_mode", String(20), nullable=False),
        Column("split_ratio", JSONB, nullable=True),
        Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now()),
    )

    op.create_table(
        "system_events",
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("event_type", String(100), nullable=False),
        Column("account_id", String(100), nullable=True),
        Column("severity", String(20), nullable=False, server_default="INFO"),
        Column("payload", JSONB, nullable=True),
        Column("created_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
    )
    op.create_index(
        "ix_system_events_type_created",
        "system_events",
        ["event_type", "created_at"],
    )
    op.create_index("ix_system_events_account", "system_events", ["account_id"])
    op.create_index("ix_system_events_severity", "system_events", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_system_events_severity", table_name="system_events")
    op.drop_index("ix_system_events_account", table_name="system_events")
    op.drop_index("ix_system_events_type_created", table_name="system_events")
    op.drop_table("system_events")
    op.drop_table("risk_profiles")
    op.drop_table("accounts")
    op.drop_index("ix_trade_history_created", table_name="trade_history")
    op.drop_index("ix_trade_history_status", table_name="trade_history")
    op.drop_index("ix_trade_history_account_pair", table_name="trade_history")
    op.drop_table("trade_history")
    op.drop_index("ix_risk_snapshots_type_account_created", table_name="risk_snapshots")
    op.drop_table("risk_snapshots")
