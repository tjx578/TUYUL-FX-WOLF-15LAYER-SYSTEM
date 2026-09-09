"""Add isolated, non-executable v3.1 activity recovery ledgers.

Revision ID: 20260909_01
Revises: 20260822_01
"""

from __future__ import annotations

from alembic import op

from storage.strategy_5scr_activity_schema import ACTIVITY_SCHEMA_SQL

revision = "20260909_01"
down_revision = "20260822_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ACTIVITY_SCHEMA_SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in ("snapshots", "attachments", "evaluations", "observations", "raw", "ledgers"):
        op.execute(f"DROP TABLE public.pair_activity_{table}_v31")
