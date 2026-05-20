"""Add event_hash dedup key to signalthrottle.signal_events when present.

Revision ID: 20260520_01
Revises: 20260321_01
Create Date: 2026-05-20 10:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260520_01"
down_revision = "20260321_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        DO $$
        BEGIN
            IF to_regclass('signalthrottle.signal_events') IS NOT NULL THEN
                EXECUTE 'ALTER TABLE signalthrottle.signal_events ADD COLUMN IF NOT EXISTS event_hash TEXT';
                EXECUTE '
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_events_event_hash
                    ON signalthrottle.signal_events(event_hash)
                ';
            ELSE
                RAISE NOTICE 'Skipping event_hash migration because signalthrottle.signal_events does not exist';
            END IF;
        END $$;
        """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        DO $$
        BEGIN
            IF to_regclass('signalthrottle.signal_events') IS NOT NULL THEN
                EXECUTE 'DROP INDEX IF EXISTS signalthrottle.idx_signal_events_event_hash';
                EXECUTE 'ALTER TABLE signalthrottle.signal_events DROP COLUMN IF EXISTS event_hash';
            END IF;
        END $$;
        """)
    )
