"""create ohlc_candles table

Revision ID: 20260315_01
Revises: 20260310_1839
Create Date: 2026-03-15 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260315_01"
down_revision = "20260310_1839"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("ohlc_candles"):
        return

    op.create_table(
        "ohlc_candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("tick_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Unique constraint: one candle per symbol+timeframe+open_time
    op.create_index(
        "uq_ohlc_symbol_tf_open",
        "ohlc_candles",
        ["symbol", "timeframe", "open_time"],
        unique=True,
    )

    # Query index: Grafana will query by symbol + timeframe + time range
    op.create_index(
        "ix_ohlc_candles_lookup",
        "ohlc_candles",
        ["symbol", "timeframe", "open_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_ohlc_candles_lookup", table_name="ohlc_candles")
    op.drop_index("uq_ohlc_symbol_tf_open", table_name="ohlc_candles")
    op.drop_table("ohlc_candles")
