"""Add durable Strategy Analysis Lifecycle V2 (market-episode identity).

Additive and shadow-only.  No existing table is altered: ``pressure_outbox``,
``strategy_5scr_inbox``, ``strategy_5scr_lifecycles`` and every transport
identity keep their current meaning and behaviour.  These tables record a
parallel market-episode grouping so it can be measured before anything depends
on it.

Revision ID: 20260729_01
Revises: 20260724_04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260729_01"
down_revision = "20260724_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_analysis_lifecycles_v2",
        sa.Column("strategy_lifecycle_id", sa.Text(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("direction_state", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_continuity_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_material_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("material_state_hash", sa.String(length=64), nullable=False),
        sa.Column("event_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("clean_block_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("watch_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        # Shadow-only enforced by the database, not merely by the Python
        # contract. A future writer cannot grant execution authority to an
        # episode by forgetting a default -- the CHECK refuses the row.
        sa.Column(
            "execution_authority",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('ANALYSIS_OPEN','TRANSITION_PENDING','TERMINAL_NO_TRADE','INVALIDATED','SUPERSEDED')",
            name="ck_5scr_lifecycle_v2_state",
        ),
        sa.CheckConstraint(
            "direction_state IN ('BUY','SELL','INCOMPLETE','CONFLICT')",
            name="ck_5scr_lifecycle_v2_direction_state",
        ),
        # Each clock is a subset of the one above it.
        sa.CheckConstraint(
            "last_continuity_event_at <= last_event_at",
            name="ck_5scr_lifecycle_v2_continuity_not_future",
        ),
        sa.CheckConstraint(
            "last_material_event_at <= last_continuity_event_at",
            name="ck_5scr_lifecycle_v2_material_not_future",
        ),
        sa.CheckConstraint("event_count >= 0", name="ck_5scr_lifecycle_v2_event_count"),
        sa.CheckConstraint(
            "execution_authority = false",
            name="ck_5scr_lifecycle_v2_shadow_only",
        ),
    )

    # Active-episode lookup during folding.  Deliberately NOT unique per symbol:
    # the shadow period exists partly to reveal whether legitimate overlapping
    # episodes occur, and a unique constraint would hide that by failing writes.
    op.create_index(
        "ix_5scr_lifecycle_v2_active_symbol",
        "strategy_5scr_analysis_lifecycles_v2",
        ["symbol", "last_continuity_event_at"],
        postgresql_where=sa.text("state IN ('ANALYSIS_OPEN', 'TRANSITION_PENDING')"),
    )

    op.create_table(
        "strategy_5scr_lifecycle_event_links_v2",
        # TEXT, not UUID: the outbox emits UUIDs but replay emits "sha256:..".
        # A UUID column would reject replayed events at insert time.
        sa.Column("pressure_event_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("transport_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("source_clean_block_id", sa.Text(), nullable=True),
        sa.Column("source_watch_id", sa.Text(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("link_reason", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_lifecycle_v2_event_link",
        ),
    )
    op.create_index(
        "ix_5scr_lifecycle_v2_links_lifecycle",
        "strategy_5scr_lifecycle_event_links_v2",
        ["strategy_lifecycle_id", "linked_at"],
    )
    # Lets the shadow audit compare transport grouping against episode grouping
    # without a sequential scan.
    op.create_index(
        "ix_5scr_lifecycle_v2_links_transport",
        "strategy_5scr_lifecycle_event_links_v2",
        ["transport_lifecycle_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_5scr_lifecycle_v2_links_transport",
        table_name="strategy_5scr_lifecycle_event_links_v2",
    )
    op.drop_index(
        "ix_5scr_lifecycle_v2_links_lifecycle",
        table_name="strategy_5scr_lifecycle_event_links_v2",
    )
    op.drop_table("strategy_5scr_lifecycle_event_links_v2")
    op.drop_index(
        "ix_5scr_lifecycle_v2_active_symbol",
        table_name="strategy_5scr_analysis_lifecycles_v2",
    )
    op.drop_table("strategy_5scr_analysis_lifecycles_v2")
