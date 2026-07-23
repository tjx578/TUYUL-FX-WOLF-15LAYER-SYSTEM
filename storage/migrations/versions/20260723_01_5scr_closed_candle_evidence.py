"""Add canonical candle provenance and durable 5S-CR evidence results.

Revision ID: 20260723_01
Revises: 20260720_02

Existing candle rows are deliberately backfilled as incomplete/unspecified.
Their timestamp authority cannot be proven retroactively, so they remain
diagnostic and cannot enter a Strategy 5S-CR evidence snapshot.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260723_01"
down_revision = "20260720_02"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("ohlc_candles"):
        candle_columns = _column_names("ohlc_candles")
        with op.batch_alter_table("ohlc_candles") as batch:
            if "complete" not in candle_columns:
                batch.add_column(
                    sa.Column(
                        "complete",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false"),
                    )
                )
            if "provider" not in candle_columns:
                batch.add_column(
                    sa.Column(
                        "provider",
                        sa.String(length=100),
                        nullable=False,
                        server_default=sa.text("'legacy_unknown'"),
                    )
                )
            if "provider_timestamp_semantics" not in candle_columns:
                batch.add_column(
                    sa.Column(
                        "provider_timestamp_semantics",
                        sa.String(length=32),
                        nullable=False,
                        server_default=sa.text("'UNSPECIFIED'"),
                    )
                )
        if "ix_ohlc_candles_closed_asof" not in _index_names("ohlc_candles"):
            op.create_index(
                "ix_ohlc_candles_closed_asof",
                "ohlc_candles",
                ["symbol", "timeframe", "close_time"],
                postgresql_where=sa.text("complete = true"),
            )

    inspector = inspect(op.get_bind())
    if inspector.has_table("strategy_5scr_inbox"):
        inbox_columns = _column_names("strategy_5scr_inbox")
        with op.batch_alter_table("strategy_5scr_inbox") as batch:
            if "result_payload" not in inbox_columns:
                batch.add_column(sa.Column("result_payload", JSONB(), nullable=True))
            if "evidence_snapshot_id" not in inbox_columns:
                batch.add_column(sa.Column("evidence_snapshot_id", sa.String(length=80), nullable=True))
            if "evidence_attempt_count" not in inbox_columns:
                batch.add_column(
                    sa.Column(
                        "evidence_attempt_count",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "evidence_last_attempt_at" not in inbox_columns:
                batch.add_column(sa.Column("evidence_last_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("strategy_5scr_inbox"):
        inbox_columns = _column_names("strategy_5scr_inbox")
        with op.batch_alter_table("strategy_5scr_inbox") as batch:
            for column_name in (
                "evidence_last_attempt_at",
                "evidence_attempt_count",
                "evidence_snapshot_id",
                "result_payload",
            ):
                if column_name in inbox_columns:
                    batch.drop_column(column_name)

    inspector = inspect(op.get_bind())
    if inspector.has_table("ohlc_candles"):
        if "ix_ohlc_candles_closed_asof" in _index_names("ohlc_candles"):
            op.drop_index("ix_ohlc_candles_closed_asof", table_name="ohlc_candles")
        candle_columns = _column_names("ohlc_candles")
        with op.batch_alter_table("ohlc_candles") as batch:
            for column_name in (
                "provider_timestamp_semantics",
                "provider",
                "complete",
            ):
                if column_name in candle_columns:
                    batch.drop_column(column_name)
