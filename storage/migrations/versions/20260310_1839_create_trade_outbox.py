"""create trade_outbox table

Revision ID: 20260310_1839
Revises: 20260310_01
Create Date: 2026-03-10 18:39:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260310_1839"
down_revision = "20260310_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("trade_outbox"):
        return

    op.create_table(
        "trade_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_trade_outbox_status_created_at",
        "trade_outbox",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_trade_outbox_trade_id",
        "trade_outbox",
        ["trade_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trade_outbox_trade_id", table_name="trade_outbox")
    op.drop_index("ix_trade_outbox_status_created_at", table_name="trade_outbox")
    op.drop_table("trade_outbox")
