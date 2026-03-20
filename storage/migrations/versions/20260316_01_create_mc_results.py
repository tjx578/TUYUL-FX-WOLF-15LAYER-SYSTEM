"""create mc_results table for Monte Carlo historical trending

Revision ID: 20260316_01
Revises: 20260315_01
Create Date: 2026-03-16 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260316_01"
down_revision = "20260315_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("mc_results"):
        return

    op.create_table(
        "mc_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("pair_count", sa.Integer(), nullable=False),
        sa.Column("simulations", sa.Integer(), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("portfolio_win_rate", sa.Float(), nullable=False),
        sa.Column("portfolio_profit_factor", sa.Float(), nullable=False),
        sa.Column("portfolio_risk_of_ruin", sa.Float(), nullable=False),
        sa.Column("portfolio_max_drawdown", sa.Float(), nullable=False),
        sa.Column("portfolio_expected_value", sa.Float(), nullable=False),
        sa.Column("diversification_ratio", sa.Float(), nullable=False),
        sa.Column("advisory_flag", sa.String(length=10), nullable=False),
        sa.Column("is_incremental", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pair_symbols", sa.Text(), nullable=False),
        sa.Column("pair_contributions", sa.Text(), nullable=True),
        sa.Column("correlation_matrix", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Time-series query: dashboard trending by advisory flag over time
    op.create_index(
        "ix_mc_results_computed_at",
        "mc_results",
        ["computed_at"],
    )

    # Lookup by run_id
    op.create_index(
        "ix_mc_results_run_id",
        "mc_results",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mc_results_run_id", table_name="mc_results")
    op.drop_index("ix_mc_results_computed_at", table_name="mc_results")
    op.drop_table("mc_results")
