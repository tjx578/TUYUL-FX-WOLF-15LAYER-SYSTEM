"""Separate immutable provider observations from selected canonical candles.

Revision ID: 20260724_02
Revises: 20260724_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260724_02"
down_revision = "20260724_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_provider_candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("feed", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_timestamp_semantics", sa.String(length=32), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("tick_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider",
            "feed",
            "symbol",
            "timeframe",
            "provider_timestamp",
            name="uq_raw_provider_candle_identity",
        ),
    )
    op.create_index(
        "ix_raw_provider_candles_window",
        "raw_provider_candles",
        ["symbol", "timeframe", "open_time", "provider"],
    )

    op.create_table(
        "canonical_candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("tick_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("selected_provider", sa.String(length=100), nullable=False),
        sa.Column("selected_feed", sa.String(length=100), nullable=False),
        sa.Column("provider_timestamp_semantics", sa.String(length=32), nullable=False),
        sa.Column("selected_raw_candle_id", sa.BigInteger(), nullable=False),
        sa.Column("selection_policy", sa.String(length=100), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["selected_raw_candle_id"],
            ["raw_provider_candles.id"],
            name="fk_canonical_selected_raw_candle",
        ),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "open_time",
            name="uq_canonical_candle_window",
        ),
    )
    op.create_index(
        "ix_canonical_candles_closed_asof",
        "canonical_candles",
        ["symbol", "timeframe", "close_time"],
        postgresql_where=sa.text("complete = true"),
    )

    # Retain only rows whose closure authority was established by the canary.
    op.execute(
        """
        INSERT INTO raw_provider_candles (
            provider, feed, symbol, timeframe, provider_timestamp,
            provider_timestamp_semantics, open_time, close_time,
            open, high, low, close, volume, tick_count, complete,
            payload_hash, metadata
        )
        SELECT provider, 'legacy_ohlc', symbol, timeframe,
               CASE provider_timestamp_semantics
                 WHEN 'PERIOD_END' THEN close_time
                 ELSE open_time
               END,
               provider_timestamp_semantics, open_time, close_time,
               open, high, low, close, volume, tick_count, complete,
               md5(concat_ws('|', provider, symbol, timeframe, open_time::text,
                              open::text, high::text, low::text, close::text)),
               '{"backfill_source":"ohlc_candles"}'::jsonb
        FROM ohlc_candles
        WHERE complete = true
          AND provider_timestamp_semantics <> 'UNSPECIFIED'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO canonical_candles (
            symbol, timeframe, open_time, close_time, open, high, low, close,
            volume, tick_count, complete, selected_provider, selected_feed,
            provider_timestamp_semantics, selected_raw_candle_id,
            selection_policy, selection_rank, content_hash
        )
        SELECT DISTINCT ON (symbol, timeframe, open_time)
               symbol, timeframe, open_time, close_time, open, high, low, close,
               volume, tick_count, complete, provider, feed,
               provider_timestamp_semantics, id,
               '5scr.provider-priority.v1',
               1000 + CASE
                 WHEN lower(provider) LIKE 'mt5%' OR lower(provider) LIKE 'broker%' THEN 300
                 WHEN lower(provider) IN ('wolf15_tick_builder', 'tick_builder') THEN 200
                 WHEN lower(provider) = 'finnhub' THEN 100
                 ELSE 50
               END,
               payload_hash
        FROM raw_provider_candles
        WHERE complete = true
        ORDER BY symbol, timeframe, open_time, last_observed_at DESC, id DESC
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_candles_closed_asof", table_name="canonical_candles")
    op.drop_table("canonical_candles")
    op.drop_index("ix_raw_provider_candles_window", table_name="raw_provider_candles")
    op.drop_table("raw_provider_candles")
