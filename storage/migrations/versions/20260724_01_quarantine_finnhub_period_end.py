"""Quarantine Finnhub candles normalized with reversed timestamp semantics.

Revision ID: 20260724_01
Revises: 20260723_01

Runtime parity proved that Finnhub's OANDA candle timestamp is the period
opening time. Rows written by the initial closed-candle canary labelled it as
PERIOD_END and shifted the canonical window backwards. They must remain
diagnostic and cannot retain closed-candle authority.
"""

from __future__ import annotations

from alembic import op

revision = "20260724_01"
down_revision = "20260723_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ohlc_candles
        SET complete = false,
            provider_timestamp_semantics = 'UNSPECIFIED'
        WHERE lower(provider) = 'finnhub'
          AND provider_timestamp_semantics = 'PERIOD_END'
        """
    )


def downgrade() -> None:
    # Safety quarantine is intentionally irreversible: a downgrade cannot
    # prove the original provider window and must not restore false authority.
    pass
