"""Add durable shadow-only Microboost pulse events and current state.

Revision ID: 20260811_01
Revises: 20260810_02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260811_01"
down_revision = "20260810_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_microboost_pulse_events_v1",
        sa.Column("pulse_event_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("transition", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_ids", JSONB(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "execution_authority",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_microboost_pulse_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "pulse_event_id ~ '^5scr-pulse:[0-9a-f]{32}$' AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_microboost_pulse_identity_v1",
        ),
        sa.CheckConstraint(
            "transition IN ('FORMED','REINFORCED','WEAKENED','INVALIDATED','EXPIRED')",
            name="ck_5scr_microboost_pulse_transition_v1",
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('BUY','SELL')",
            name="ck_5scr_microboost_pulse_direction_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_event_ids) = 'array' AND jsonb_array_length(source_event_ids) > 0",
            name="ck_5scr_microboost_pulse_sources_v1",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE",
            name="ck_5scr_microboost_pulse_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_microboost_pulse_dedupe_v1",
        "strategy_5scr_microboost_pulse_events_v1",
        ["dedupe_key"],
        unique=True,
    )
    op.create_index(
        "ix_5scr_microboost_pulse_lifecycle_time_v1",
        "strategy_5scr_microboost_pulse_events_v1",
        ["strategy_lifecycle_id", "occurred_at", "pulse_event_id"],
    )

    op.create_table(
        "strategy_5scr_microboost_states_v1",
        sa.Column("strategy_lifecycle_id", sa.Text(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=True),
        sa.Column("first_formed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pulse_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("independent_pulse_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reinforcement_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("carried_snapshot_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("observed_snapshot_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_effective_ticks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("peak_effective_ticks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_strength", sa.String(length=100), nullable=True),
        sa.Column("peak_strength", sa.String(length=100), nullable=True),
        sa.Column("active_block_id", sa.Text(), nullable=True),
        sa.Column("last_source_stage", sa.String(length=100), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_source_event_id", sa.Text(), nullable=False),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "execution_authority",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_microboost_state_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "state IN ('NONE','ACTIVE','WEAKENING','INVALIDATED','EXPIRED')",
            name="ck_5scr_microboost_state_name_v1",
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('BUY','SELL')",
            name="ck_5scr_microboost_state_direction_v1",
        ),
        sa.CheckConstraint(
            "independent_pulse_count >= 0 AND reinforcement_count >= 0 "
            "AND carried_snapshot_count >= 0 AND observed_snapshot_count >= 0 "
            "AND current_effective_ticks >= 0 AND peak_effective_ticks >= current_effective_ticks "
            "AND state_version >= 0",
            name="ck_5scr_microboost_state_counters_v1",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_microboost_state_evidence_v1",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE",
            name="ck_5scr_microboost_state_shadow_only_v1",
        ),
    )
    op.create_index(
        "ix_5scr_microboost_state_status_v1",
        "strategy_5scr_microboost_states_v1",
        ["state", "last_observed_at", "strategy_lifecycle_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_5scr_microboost_state_status_v1",
        table_name="strategy_5scr_microboost_states_v1",
    )
    op.drop_table("strategy_5scr_microboost_states_v1")
    op.drop_index(
        "ix_5scr_microboost_pulse_lifecycle_time_v1",
        table_name="strategy_5scr_microboost_pulse_events_v1",
    )
    op.drop_index(
        "uq_5scr_microboost_pulse_dedupe_v1",
        table_name="strategy_5scr_microboost_pulse_events_v1",
    )
    op.drop_table("strategy_5scr_microboost_pulse_events_v1")
