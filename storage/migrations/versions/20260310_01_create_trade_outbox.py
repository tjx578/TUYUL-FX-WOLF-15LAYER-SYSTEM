"""Reconcile trade_outbox migration chain safely.

Revision ID: 20260310_01
Revises: 003_trade_outbox
Create Date: 2026-03-10

Why this exists:
- `trade_outbox` is already created in `003_trade_outbox`.
- Re-creating the same table in this revision would fail on upgrade.

Behavior:
- If the table already exists: no-op.
- If the table is unexpectedly missing: create the canonical schema used by runtime code.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260310_01"
down_revision = "003_trade_outbox"
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
    # No-op downgrade: this revision is reconciliation-only and should not
    # remove a table introduced by an earlier migration in the chain.
    return
