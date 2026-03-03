"""Add canonical governance tables for accounts, prop firms, and EA instances."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_governance_models"
down_revision = "001_initial"
branch_labels = None
depends_on = None


risk_profile_enum = sa.Enum("Conservative", "Balanced", "Aggressive", name="risk_profile_level")
account_mode_enum = sa.Enum("PAPER", "LIVE", name="account_mode")
ea_status_enum = sa.Enum("RUNNING", "STOPPED", name="ea_status")
strategy_type_enum = sa.Enum("H1_SWING", "M15_SCALP", name="strategy_type")


def upgrade() -> None:
    bind = op.get_bind()
    risk_profile_enum.create(bind, checkfirst=True)
    account_mode_enum.create(bind, checkfirst=True)
    ea_status_enum.create(bind, checkfirst=True)
    strategy_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "prop_firm_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("max_daily_loss", sa.Float(), nullable=False),
        sa.Column("max_total_loss", sa.Float(), nullable=False),
        sa.Column("profit_target", sa.Float(), nullable=False),
        sa.Column("consistency_rule", sa.String(length=255), nullable=False),
        sa.Column("phase", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "core_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("broker", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("equity_high", sa.Float(), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("risk_profile", risk_profile_enum, nullable=False, server_default="Balanced"),
        sa.Column("prop_firm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", account_mode_enum, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prop_firm_id"], ["prop_firm_rules.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_core_accounts_prop_firm_id", "core_accounts", ["prop_firm_id"], unique=False)
    op.create_index("ix_core_accounts_active", "core_accounts", ["active"], unique=False)

    op.create_table(
        "ea_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("strategy_type", strategy_type_enum, nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", ea_status_enum, nullable=False, server_default="STOPPED"),
        sa.Column("safe_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["core_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "name", name="uq_ea_instances_account_name"),
    )
    op.create_index("ix_ea_instances_account_id", "ea_instances", ["account_id"], unique=False)
    op.create_index("ix_ea_instances_status", "ea_instances", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ea_instances_status", table_name="ea_instances")
    op.drop_index("ix_ea_instances_account_id", table_name="ea_instances")
    op.drop_table("ea_instances")

    op.drop_index("ix_core_accounts_active", table_name="core_accounts")
    op.drop_index("ix_core_accounts_prop_firm_id", table_name="core_accounts")
    op.drop_table("core_accounts")

    op.drop_table("prop_firm_rules")

    bind = op.get_bind()
    strategy_type_enum.drop(bind, checkfirst=True)
    ea_status_enum.drop(bind, checkfirst=True)
    account_mode_enum.drop(bind, checkfirst=True)
    risk_profile_enum.drop(bind, checkfirst=True)
