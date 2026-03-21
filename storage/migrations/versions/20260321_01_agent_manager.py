"""Agent Manager — create ea_profiles, ea_agents, ea_agent_runtime, ea_agent_events,
ea_agent_audit_logs, account_portfolio_snapshots tables.

NOTE: ea_instances table (from 002_governance_models.py) is deprecated in favour of
ea_agents but both coexist during transition. Do NOT drop ea_instances here.

Revision ID: 20260321_01
Revises: 20260316_01
Create Date: 2026-03-21 11:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260321_01"
down_revision = "20260316_01"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Enum definitions — all NEW names to avoid collision with existing pg enums
# ---------------------------------------------------------------------------

# create_type=False prevents SQLAlchemy from auto-creating these via table
# before_create events.  We create them explicitly with idempotent raw SQL.
_EA_CLASS_ENUM = sa.Enum(
    "PRIMARY",
    "PORTFOLIO",
    name="ea_class_enum",
    create_type=False,
)

_EA_SUBTYPE_ENUM = sa.Enum(
    "BROKER",
    "PROP_FIRM",
    "EDUMB",
    "STANDARD_REPORTER",
    name="ea_subtype_enum",
    create_type=False,
)

_EXECUTION_MODE_ENUM = sa.Enum(
    "LIVE",
    "DEMO",
    "SHADOW",
    name="execution_mode_enum",
    create_type=False,
)

_REPORTER_MODE_ENUM = sa.Enum(
    "FULL",
    "BALANCE_ONLY",
    "DISABLED",
    name="reporter_mode_enum",
    create_type=False,
)

# Distinct from existing `ea_status` enum (RUNNING/STOPPED) used by ea_instances.
_EA_AGENT_STATUS_ENUM = sa.Enum(
    "ONLINE",
    "WARNING",
    "OFFLINE",
    "QUARANTINED",
    "DISABLED",
    name="ea_agent_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # -- Create enum types idempotently (survives partial prior runs) --------
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE ea_class_enum AS ENUM ('PRIMARY', 'PORTFOLIO');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE ea_subtype_enum AS ENUM ('BROKER', 'PROP_FIRM', 'EDUMB', 'STANDARD_REPORTER');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE execution_mode_enum AS ENUM ('LIVE', 'DEMO', 'SHADOW');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE reporter_mode_enum AS ENUM ('FULL', 'BALANCE_ONLY', 'DISABLED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE ea_agent_status AS ENUM ('ONLINE', 'WARNING', 'OFFLINE', 'QUARANTINED', 'DISABLED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))

    # -- ea_profiles ----------------------------------------------------------
    if not inspector.has_table("ea_profiles"):
        op.create_table(
            "ea_profiles",
            sa.Column(
                "id",
                sa.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("profile_name", sa.String(100), unique=True, nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "ea_class",
                sa.Enum("PRIMARY", "PORTFOLIO", name="ea_class_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "ea_subtype",
                sa.Enum(
                    "BROKER",
                    "PROP_FIRM",
                    "EDUMB",
                    "STANDARD_REPORTER",
                    name="ea_subtype_enum",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "execution_mode",
                sa.Enum("LIVE", "DEMO", "SHADOW", name="execution_mode_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "reporter_mode",
                sa.Enum(
                    "FULL",
                    "BALANCE_ONLY",
                    "DISABLED",
                    name="reporter_mode_enum",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "default_risk_multiplier",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "default_news_lock",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'DEFAULT'"),
            ),
            sa.Column(
                "allowed_strategies",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
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
        )

    # -- ea_agents ------------------------------------------------------------
    if not inspector.has_table("ea_agents"):
        op.create_table(
            "ea_agents",
            sa.Column(
                "id",
                sa.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("agent_name", sa.String(150), nullable=False),
            sa.Column(
                "ea_class",
                sa.Enum("PRIMARY", "PORTFOLIO", name="ea_class_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "ea_subtype",
                sa.Enum(
                    "BROKER",
                    "PROP_FIRM",
                    "EDUMB",
                    "STANDARD_REPORTER",
                    name="ea_subtype_enum",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "execution_mode",
                sa.Enum("LIVE", "DEMO", "SHADOW", name="execution_mode_enum", create_type=False),
                nullable=False,
                server_default=sa.text("'DEMO'"),
            ),
            sa.Column(
                "reporter_mode",
                sa.Enum(
                    "FULL",
                    "BALANCE_ONLY",
                    "DISABLED",
                    name="reporter_mode_enum",
                    create_type=False,
                ),
                nullable=False,
                server_default=sa.text("'FULL'"),
            ),
            # ea_agent_status is DISTINCT from ea_status (RUNNING/STOPPED) used by ea_instances
            sa.Column(
                "status",
                sa.Enum(
                    "ONLINE",
                    "WARNING",
                    "OFFLINE",
                    "QUARANTINED",
                    "DISABLED",
                    name="ea_agent_status",
                    create_type=False,
                ),
                nullable=False,
                server_default=sa.text("'OFFLINE'"),
            ),
            # Nullable UUID — no FK constraint as accounts table may lack UUID PK yet
            sa.Column("linked_account_id", sa.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "linked_profile_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_profiles.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("mt5_login", sa.BigInteger(), nullable=True),
            sa.Column("mt5_server", sa.String(200), nullable=True),
            sa.Column("broker_name", sa.String(200), nullable=True),
            sa.Column(
                "strategy_profile",
                sa.String(100),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column(
                "risk_multiplier",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "news_lock_setting",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'DEFAULT'"),
            ),
            sa.Column("auth_key_hash", sa.String(255), nullable=True),
            sa.Column("safe_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("lock_reason", sa.Text(), nullable=True),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_by", sa.String(100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("version", sa.String(50), nullable=True),
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
        )

        # Partial unique index: (mt5_login, mt5_server) WHERE both NOT NULL
        op.create_index(
            "ix_ea_agents_mt5_login_server",
            "ea_agents",
            ["mt5_login", "mt5_server"],
            unique=True,
            postgresql_where=sa.text("mt5_login IS NOT NULL AND mt5_server IS NOT NULL"),
        )

    # -- ea_agent_runtime -----------------------------------------------------
    if not inspector.has_table("ea_agent_runtime"):
        op.create_table(
            "ea_agent_runtime",
            sa.Column(
                "agent_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_agents.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failure", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column(
                "trades_executed",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "trades_failed",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "uptime_seconds",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("cpu_usage_pct", sa.Float(), nullable=True),
            sa.Column("memory_mb", sa.Float(), nullable=True),
            sa.Column("connection_latency_ms", sa.Float(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    # -- ea_agent_events ------------------------------------------------------
    if not inspector.has_table("ea_agent_events"):
        op.create_table(
            "ea_agent_events",
            sa.Column(
                "id",
                sa.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "agent_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column(
                "severity",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'INFO'"),
            ),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_ea_agent_events_agent_created",
            "ea_agent_events",
            ["agent_id", sa.text("created_at DESC")],
        )

    # -- ea_agent_audit_logs --------------------------------------------------
    if not inspector.has_table("ea_agent_audit_logs"):
        op.create_table(
            "ea_agent_audit_logs",
            sa.Column(
                "id",
                sa.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "agent_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column(
                "performed_by",
                sa.String(100),
                nullable=False,
                server_default=sa.text("'SYSTEM'"),
            ),
            sa.Column(
                "details",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("previous_state", sa.JSON(), nullable=True),
            sa.Column("new_state", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_ea_agent_audit_logs_agent_created",
            "ea_agent_audit_logs",
            ["agent_id", sa.text("created_at DESC")],
        )

    # -- account_portfolio_snapshots ------------------------------------------
    if not inspector.has_table("account_portfolio_snapshots"):
        op.create_table(
            "account_portfolio_snapshots",
            sa.Column(
                "id",
                sa.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "agent_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("ea_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("balance", sa.Float(), nullable=False),
            sa.Column("equity", sa.Float(), nullable=False),
            sa.Column(
                "margin_used",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "margin_free",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "open_positions",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "daily_pnl",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "floating_pnl",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "snapshot_source",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'MT5'"),
            ),
            sa.Column(
                "captured_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_account_portfolio_snapshots_agent_captured",
            "account_portfolio_snapshots",
            ["agent_id", sa.text("captured_at DESC")],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_account_portfolio_snapshots_agent_captured",
        table_name="account_portfolio_snapshots",
    )
    op.drop_table("account_portfolio_snapshots")

    op.drop_index("ix_ea_agent_audit_logs_agent_created", table_name="ea_agent_audit_logs")
    op.drop_table("ea_agent_audit_logs")

    op.drop_index("ix_ea_agent_events_agent_created", table_name="ea_agent_events")
    op.drop_table("ea_agent_events")

    op.drop_table("ea_agent_runtime")

    op.drop_index("ix_ea_agents_mt5_login_server", table_name="ea_agents")
    op.drop_table("ea_agents")

    op.drop_table("ea_profiles")

    op.execute(sa.text("DROP TYPE IF EXISTS ea_agent_status"))
    op.execute(sa.text("DROP TYPE IF EXISTS reporter_mode_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS execution_mode_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS ea_subtype_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS ea_class_enum"))
