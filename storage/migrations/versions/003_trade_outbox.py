"""Add durable trade_outbox table for transactional outbox pattern."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op as _op  # pyright: ignore[reportMissingImports]
from sqlalchemy.dialects.postgresql import JSONB

op: Any = _op

revision = "003_trade_outbox"
down_revision = "002_governance_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("outbox_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column("outbox_key", sa.String(length=150), nullable=False, unique=True),
        sa.Column("trade_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_trade_outbox_status_next_attempt",
        "trade_outbox",
        ["status", "next_attempt_at"],
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
    op.drop_index("ix_trade_outbox_status_next_attempt", table_name="trade_outbox")
    op.drop_table("trade_outbox")
