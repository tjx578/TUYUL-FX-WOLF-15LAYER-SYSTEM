"""Add durable, shadow-only Strategy 5S-CR ContextEpoch V1.

Material context identity is intentionally separate from lifecycle, thesis,
execution box, campaign, and command identity.  The schema records contiguous
context epochs and their append-only boundaries without granting execution
authority or wiring a production consumer.

Revision ID: 20260812_01
Revises: 20260811_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260812_01"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_context_epochs_v1",
        sa.Column("context_epoch_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("epoch_sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_source_candle_ids", JSONB(), nullable=False),
        sa.Column("h4_source_candle_ids", JSONB(), nullable=False),
        sa.Column("daily_bias", sa.String(length=100), nullable=False),
        sa.Column("h4_structure", sa.String(length=100), nullable=False),
        sa.Column("price_location", sa.String(length=100), nullable=False),
        sa.Column("liquidity_state", sa.String(length=100), nullable=False),
        sa.Column("direction_domain", sa.String(length=24), nullable=False),
        sa.Column("allowed_routes", JSONB(), nullable=False),
        sa.Column("blocked_routes", JSONB(), nullable=False),
        sa.Column("target_map_version", sa.String(length=100), nullable=True),
        sa.Column("structural_invalidation_version", sa.String(length=100), nullable=True),
        sa.Column("transition_reason", sa.String(length=32), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_source_event_id", sa.Text(), nullable=False),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_context_epoch_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "strategy_lifecycle_id",
            "epoch_sequence",
            name="uq_5scr_context_epoch_sequence_v1",
        ),
        sa.CheckConstraint(
            "context_epoch_id ~ '^5scr-context:[0-9a-f]{32}$' "
            "AND material_context_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_context_epoch_identity_v1",
        ),
        sa.CheckConstraint(
            "epoch_sequence >= 1 AND state_version >= 1",
            name="ck_5scr_context_epoch_versions_v1",
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE','SUPERSEDED','TERMINAL')",
            name="ck_5scr_context_epoch_state_v1",
        ),
        sa.CheckConstraint(
            "direction_domain IN ('BUY_ONLY','SELL_ONLY','BOTH_CONDITIONAL','UNRESOLVED','EMPTY')",
            name="ck_5scr_context_epoch_direction_v1",
        ),
        sa.CheckConstraint(
            "transition_reason IN ('OPENED','MATERIAL_CONTEXT_CHANGED','LIFECYCLE_TERMINAL')",
            name="ck_5scr_context_epoch_reason_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(daily_source_candle_ids) = 'array' "
            "AND jsonb_array_length(daily_source_candle_ids) > 0 "
            "AND jsonb_typeof(h4_source_candle_ids) = 'array' "
            "AND jsonb_array_length(h4_source_candle_ids) > 0 "
            "AND jsonb_typeof(allowed_routes) = 'array' "
            "AND jsonb_typeof(blocked_routes) = 'array'",
            name="ck_5scr_context_epoch_evidence_arrays_v1",
        ),
        sa.CheckConstraint(
            "last_confirmed_at >= opened_at AND last_observed_at >= opened_at "
            "AND ((state = 'ACTIVE' AND closed_at IS NULL) "
            "OR (state IN ('SUPERSEDED','TERMINAL') AND closed_at >= last_confirmed_at "
            "AND closed_at >= last_observed_at))",
            name="ck_5scr_context_epoch_temporal_v1",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE",
            name="ck_5scr_context_epoch_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_context_active_lifecycle_v1",
        "strategy_5scr_context_epochs_v1",
        ["strategy_lifecycle_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "ix_5scr_context_lifecycle_history_v1",
        "strategy_5scr_context_epochs_v1",
        ["strategy_lifecycle_id", "epoch_sequence", "context_epoch_id"],
    )

    op.create_table(
        "strategy_5scr_context_transitions_v1",
        sa.Column("transition_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("from_context_epoch_id", sa.Text(), nullable=True),
        sa.Column("to_context_epoch_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("source_pressure_event_id", sa.Text(), nullable=False),
        sa.Column("source_event_ids", JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
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
            name="fk_5scr_context_transition_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_context_epoch_id"],
            ["strategy_5scr_context_epochs_v1.context_epoch_id"],
            name="fk_5scr_context_transition_from_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_context_epoch_id"],
            ["strategy_5scr_context_epochs_v1.context_epoch_id"],
            name="fk_5scr_context_transition_to_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_pressure_event_id"],
            ["strategy_5scr_lifecycle_event_links_v2.pressure_event_id"],
            name="fk_5scr_context_transition_source_v1",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "transition_id ~ '^5scr-context-transition:[0-9a-f]{32}$' "
            "AND material_context_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_context_transition_identity_v1",
        ),
        sa.CheckConstraint(
            "(reason = 'OPENED' AND from_context_epoch_id IS NULL AND to_context_epoch_id IS NOT NULL) "
            "OR (reason = 'MATERIAL_CONTEXT_CHANGED' AND from_context_epoch_id IS NOT NULL "
            "AND to_context_epoch_id IS NOT NULL AND from_context_epoch_id <> to_context_epoch_id) "
            "OR (reason = 'LIFECYCLE_TERMINAL' AND from_context_epoch_id IS NOT NULL "
            "AND to_context_epoch_id IS NULL)",
            name="ck_5scr_context_transition_shape_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_event_ids) = 'array' AND jsonb_array_length(source_event_ids) > 0",
            name="ck_5scr_context_transition_sources_v1",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE",
            name="ck_5scr_context_transition_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_context_transition_dedupe_v1",
        "strategy_5scr_context_transitions_v1",
        ["dedupe_key"],
        unique=True,
    )
    op.create_index(
        "ix_5scr_context_transition_lifecycle_time_v1",
        "strategy_5scr_context_transitions_v1",
        ["strategy_lifecycle_id", "occurred_at", "transition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_5scr_context_transition_lifecycle_time_v1",
        table_name="strategy_5scr_context_transitions_v1",
    )
    op.drop_index(
        "uq_5scr_context_transition_dedupe_v1",
        table_name="strategy_5scr_context_transitions_v1",
    )
    op.drop_table("strategy_5scr_context_transitions_v1")
    op.drop_index(
        "ix_5scr_context_lifecycle_history_v1",
        table_name="strategy_5scr_context_epochs_v1",
    )
    op.drop_index(
        "uq_5scr_context_active_lifecycle_v1",
        table_name="strategy_5scr_context_epochs_v1",
    )
    op.drop_table("strategy_5scr_context_epochs_v1")
