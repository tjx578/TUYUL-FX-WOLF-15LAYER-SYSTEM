"""Add durable, shadow-only Strategy 5S-CR TradePlanCandidate V2.

Revision ID: 20260813_01
Revises: 20260812_03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260813_01"
down_revision = "20260812_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bind P6 rows to the exact material P3/P4 occurrences, not merely their
    # human-readable IDs.  These additive unique authorities are referenced
    # by both candidates and every-attempt evaluations.
    op.create_unique_constraint(
        "uq_5scr_context_epoch_tradeplan_scope_v1",
        "strategy_5scr_context_epochs_v1",
        ["context_epoch_id", "strategy_lifecycle_id", "symbol", "material_context_hash"],
    )
    op.create_unique_constraint(
        "uq_5scr_thesis_tradeplan_scope_v1",
        "strategy_5scr_directional_theses_v1",
        [
            "strategy_thesis_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "symbol",
            "strategy_direction",
            "semantic_identity_hash",
        ],
    )
    # P6 must bind to the exact immutable/frozen P5 occurrence.  This unique
    # authority scope is additive and remains inert until a P6 writer is
    # explicitly enabled.
    op.create_unique_constraint(
        "uq_5scr_execution_box_tradeplan_scope_v1",
        "strategy_5scr_execution_boxes_v1",
        [
            "execution_box_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "symbol",
            "strategy_direction",
            "material_box_hash",
            "freeze_authority_hash",
        ],
    )
    # Every evaluation, including a durable WAIT while P5 is still BUILDING,
    # binds the exact material box occurrence.  Freeze authority is not yet
    # available in BUILDING, so evaluation scope deliberately excludes it;
    # candidate rows retain the stricter freeze-bound authority above.
    op.create_unique_constraint(
        "uq_5scr_execution_box_tradeplan_evaluation_scope_v1",
        "strategy_5scr_execution_boxes_v1",
        [
            "execution_box_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "symbol",
            "strategy_direction",
            "material_box_hash",
        ],
    )

    op.create_table(
        "strategy_5scr_tradeplan_candidates_v2",
        sa.Column("tradeplan_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("execution_box_id", sa.Text(), nullable=False),
        sa.Column("candidate_sequence", sa.Integer(), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("previous_tradeplan_id", sa.Text(), nullable=True),
        sa.Column("previous_candidate_sequence", sa.Integer(), nullable=True),
        sa.Column("previous_candidate_revision", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("candidate_status", sa.String(length=40), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False),
        sa.Column("route_type", sa.String(length=120), nullable=False),
        sa.Column("candidate_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("stop_loss", sa.Numeric(28, 12), nullable=False),
        sa.Column("target_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("risk_distance_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("target_distance_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("rr", sa.Numeric(28, 12), nullable=False),
        sa.Column("pip_size", sa.Numeric(28, 12), nullable=False),
        sa.Column("target_mode", sa.String(length=100), nullable=False),
        sa.Column("broker_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("broker_geometry_material_hash", sa.String(length=71), nullable=False),
        sa.Column("broker_digits", sa.Integer(), nullable=False),
        sa.Column("broker_point", sa.Numeric(28, 12), nullable=False),
        sa.Column("broker_tick_size", sa.Numeric(28, 12), nullable=False),
        sa.Column("broker_pip_size", sa.Numeric(28, 12), nullable=False),
        sa.Column("broker_spread_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("material_box_hash", sa.String(length=71), nullable=False),
        sa.Column("execution_box_freeze_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("thesis_semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("box_sequence", sa.Integer(), nullable=False),
        sa.Column("box_version", sa.Integer(), nullable=False),
        sa.Column("structural_target_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("structural_target_material_hash", sa.String(length=71), nullable=False),
        sa.Column("target_map_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("structural_stop_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("material_candidate_hash", sa.String(length=71), nullable=False),
        sa.Column("formation_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("source_candle_ids", JSONB(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "next_required_stage",
            sa.String(length=40),
            nullable=False,
            server_default="RISK_RESERVATION",
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("target_authority_payload", JSONB(), nullable=False),
        sa.Column("stop_authority_payload", JSONB(), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_tradeplan_candidate_v2_lifecycle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol", "material_context_hash"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
                "strategy_5scr_context_epochs_v1.material_context_hash",
            ],
            name="fk_5scr_tradeplan_candidate_v2_context_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "strategy_thesis_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "symbol",
                "strategy_direction",
                "thesis_semantic_identity_hash",
            ],
            [
                "strategy_5scr_directional_theses_v1.strategy_thesis_id",
                "strategy_5scr_directional_theses_v1.strategy_lifecycle_id",
                "strategy_5scr_directional_theses_v1.context_epoch_id",
                "strategy_5scr_directional_theses_v1.symbol",
                "strategy_5scr_directional_theses_v1.strategy_direction",
                "strategy_5scr_directional_theses_v1.semantic_identity_hash",
            ],
            name="fk_5scr_tradeplan_candidate_v2_thesis_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "execution_box_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "symbol",
                "strategy_direction",
                "material_box_hash",
                "execution_box_freeze_authority_hash",
            ],
            [
                "strategy_5scr_execution_boxes_v1.execution_box_id",
                "strategy_5scr_execution_boxes_v1.strategy_lifecycle_id",
                "strategy_5scr_execution_boxes_v1.context_epoch_id",
                "strategy_5scr_execution_boxes_v1.strategy_thesis_id",
                "strategy_5scr_execution_boxes_v1.symbol",
                "strategy_5scr_execution_boxes_v1.strategy_direction",
                "strategy_5scr_execution_boxes_v1.material_box_hash",
                "strategy_5scr_execution_boxes_v1.freeze_authority_hash",
            ],
            name="fk_5scr_tradeplan_candidate_v2_execution_box_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "previous_tradeplan_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "execution_box_id",
                "symbol",
                "strategy_direction",
                "material_context_hash",
                "thesis_semantic_identity_hash",
                "previous_candidate_sequence",
                "previous_candidate_revision",
            ],
            [
                "strategy_5scr_tradeplan_candidates_v2.tradeplan_id",
                "strategy_5scr_tradeplan_candidates_v2.strategy_lifecycle_id",
                "strategy_5scr_tradeplan_candidates_v2.context_epoch_id",
                "strategy_5scr_tradeplan_candidates_v2.strategy_thesis_id",
                "strategy_5scr_tradeplan_candidates_v2.execution_box_id",
                "strategy_5scr_tradeplan_candidates_v2.symbol",
                "strategy_5scr_tradeplan_candidates_v2.strategy_direction",
                "strategy_5scr_tradeplan_candidates_v2.material_context_hash",
                "strategy_5scr_tradeplan_candidates_v2.thesis_semantic_identity_hash",
                "strategy_5scr_tradeplan_candidates_v2.candidate_sequence",
                "strategy_5scr_tradeplan_candidates_v2.candidate_revision",
            ],
            name="fk_5scr_tradeplan_candidate_v2_previous_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tradeplan_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "execution_box_id",
            "symbol",
            "strategy_direction",
            "material_context_hash",
            "thesis_semantic_identity_hash",
            "candidate_sequence",
            "candidate_revision",
            "material_candidate_hash",
            name="uq_5scr_tradeplan_candidate_v2_evaluation_scope",
        ),
        sa.UniqueConstraint(
            "tradeplan_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "execution_box_id",
            "symbol",
            "strategy_direction",
            "material_context_hash",
            "thesis_semantic_identity_hash",
            "candidate_sequence",
            "candidate_revision",
            name="uq_5scr_tradeplan_candidate_v2_predecessor_scope",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "candidate_sequence",
            name="uq_5scr_tradeplan_candidate_v2_sequence",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "candidate_sequence",
            "candidate_revision",
            name="uq_5scr_tradeplan_candidate_v2_revision",
        ),
        sa.CheckConstraint(
            "tradeplan_id ~ '^5scr-tradeplan-v2:[0-9a-f]{32}$' AND "
            "material_box_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "execution_box_freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "structural_target_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "structural_target_material_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "target_map_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "structural_stop_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "broker_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "broker_geometry_material_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "material_context_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "thesis_semantic_identity_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "material_candidate_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "formation_evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_tradeplan_candidate_v2_identity",
        ),
        sa.CheckConstraint(
            "candidate_sequence >= 1 AND candidate_revision >= 1 AND box_sequence >= 1 "
            "AND box_version >= 1 AND state_version >= 1 AND "
            "candidate_price > 0 AND stop_loss > 0 AND target_price > 0 AND "
            "risk_distance_price > 0 AND target_distance_price > 0 AND rr > 0 AND pip_size > 0 AND "
            "broker_digits BETWEEN 0 AND 12 AND broker_point > 0 AND broker_tick_size > 0 AND "
            "broker_pip_size > 0 AND broker_spread_price >= 0 AND "
            "broker_point <= broker_tick_size AND pip_size = broker_pip_size",
            name="ck_5scr_tradeplan_candidate_v2_numbers",
        ),
        sa.CheckConstraint(
            "strategy_direction IN ('BUY','SELL') AND "
            "((strategy_direction = 'BUY' AND stop_loss < candidate_price AND candidate_price < target_price) OR "
            "(strategy_direction = 'SELL' AND target_price < candidate_price AND candidate_price < stop_loss)) AND "
            "abs(risk_distance_price - abs(candidate_price - stop_loss)) <= 1e-12 AND "
            "abs(target_distance_price - abs(target_price - candidate_price)) <= 1e-12 AND "
            "abs(rr - (target_distance_price / risk_distance_price)) <= 1e-9",
            name="ck_5scr_tradeplan_candidate_v2_geometry",
        ),
        sa.CheckConstraint(
            "candidate_status = 'TRADEPLAN_CANDIDATE' AND "
            "lifecycle_state IN ('ACTIVE','SUPERSEDED','INVALIDATED','EXPIRED')",
            name="ck_5scr_tradeplan_candidate_v2_state",
        ),
        sa.CheckConstraint(
            "candidate_revision = 1 AND ((candidate_sequence = 1 AND previous_tradeplan_id IS NULL "
            "AND previous_candidate_sequence IS NULL AND previous_candidate_revision IS NULL) OR "
            "(candidate_sequence > 1 AND previous_tradeplan_id IS NOT NULL "
            "AND previous_candidate_sequence = candidate_sequence - 1 "
            "AND previous_candidate_revision = 1))",
            name="ck_5scr_tradeplan_candidate_v2_lineage",
        ),
        sa.CheckConstraint(
            "(lifecycle_state = 'ACTIVE' AND superseded_at IS NULL AND invalidated_at IS NULL "
            "AND expired_at IS NULL) OR "
            "(lifecycle_state = 'SUPERSEDED' AND superseded_at >= opened_at "
            "AND invalidated_at IS NULL AND expired_at IS NULL) OR "
            "(lifecycle_state = 'INVALIDATED' AND invalidated_at >= opened_at "
            "AND superseded_at IS NULL AND expired_at IS NULL) OR "
            "(lifecycle_state = 'EXPIRED' AND expired_at >= opened_at "
            "AND superseded_at IS NULL AND invalidated_at IS NULL)",
            name="ck_5scr_tradeplan_candidate_v2_temporal",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_candle_ids) = 'array' AND jsonb_array_length(source_candle_ids) > 0 "
            "AND jsonb_typeof(payload) = 'object' "
            "AND jsonb_typeof(target_authority_payload) = 'object' "
            "AND jsonb_typeof(stop_authority_payload) = 'object' "
            "AND jsonb_typeof(evidence_payload) = 'object'",
            name="ck_5scr_tradeplan_candidate_v2_payloads",
        ),
        sa.CheckConstraint(
            "valid_for_execution IS FALSE AND execution_authority IS FALSE "
            "AND next_required_stage = 'RISK_RESERVATION'",
            name="ck_5scr_tradeplan_candidate_v2_shadow_only",
        ),
    )
    op.create_index(
        "uq_5scr_tradeplan_candidate_v2_active_box",
        "strategy_5scr_tradeplan_candidates_v2",
        ["execution_box_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_state = 'ACTIVE'"),
    )
    op.create_index(
        "uq_5scr_tradeplan_candidate_v2_active_lifecycle",
        "strategy_5scr_tradeplan_candidates_v2",
        ["strategy_lifecycle_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_state = 'ACTIVE'"),
    )
    op.create_index(
        "ix_5scr_tradeplan_candidate_v2_lifecycle_history",
        "strategy_5scr_tradeplan_candidates_v2",
        ["strategy_lifecycle_id", "candidate_sequence", "tradeplan_id"],
    )

    op.create_table(
        "strategy_5scr_tradeplan_candidate_evaluations_v2",
        sa.Column("evaluation_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("execution_box_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("thesis_semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("material_box_hash", sa.String(length=71), nullable=False),
        sa.Column("execution_box_freeze_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("evaluation_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_request_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("reason_codes", JSONB(), nullable=False),
        sa.Column("material_evaluation_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=True),
        sa.Column("candidate_sequence", sa.Integer(), nullable=True),
        sa.Column("candidate_revision", sa.Integer(), nullable=True),
        sa.Column("material_candidate_hash", sa.String(length=71), nullable=True),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("target_authority_payload", JSONB(), nullable=False),
        sa.Column("stop_authority_payload", JSONB(), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            [
                "execution_box_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "symbol",
                "strategy_direction",
                "material_box_hash",
            ],
            [
                "strategy_5scr_execution_boxes_v1.execution_box_id",
                "strategy_5scr_execution_boxes_v1.strategy_lifecycle_id",
                "strategy_5scr_execution_boxes_v1.context_epoch_id",
                "strategy_5scr_execution_boxes_v1.strategy_thesis_id",
                "strategy_5scr_execution_boxes_v1.symbol",
                "strategy_5scr_execution_boxes_v1.strategy_direction",
                "strategy_5scr_execution_boxes_v1.material_box_hash",
            ],
            name="fk_5scr_tradeplan_candidate_evaluation_v2_box_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol", "material_context_hash"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
                "strategy_5scr_context_epochs_v1.material_context_hash",
            ],
            name="fk_5scr_tradeplan_candidate_evaluation_v2_context_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "strategy_thesis_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "symbol",
                "strategy_direction",
                "thesis_semantic_identity_hash",
            ],
            [
                "strategy_5scr_directional_theses_v1.strategy_thesis_id",
                "strategy_5scr_directional_theses_v1.strategy_lifecycle_id",
                "strategy_5scr_directional_theses_v1.context_epoch_id",
                "strategy_5scr_directional_theses_v1.symbol",
                "strategy_5scr_directional_theses_v1.strategy_direction",
                "strategy_5scr_directional_theses_v1.semantic_identity_hash",
            ],
            name="fk_5scr_tradeplan_candidate_evaluation_v2_thesis_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "tradeplan_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "execution_box_id",
                "symbol",
                "strategy_direction",
                "material_context_hash",
                "thesis_semantic_identity_hash",
                "candidate_sequence",
                "candidate_revision",
                "material_candidate_hash",
            ],
            [
                "strategy_5scr_tradeplan_candidates_v2.tradeplan_id",
                "strategy_5scr_tradeplan_candidates_v2.strategy_lifecycle_id",
                "strategy_5scr_tradeplan_candidates_v2.context_epoch_id",
                "strategy_5scr_tradeplan_candidates_v2.strategy_thesis_id",
                "strategy_5scr_tradeplan_candidates_v2.execution_box_id",
                "strategy_5scr_tradeplan_candidates_v2.symbol",
                "strategy_5scr_tradeplan_candidates_v2.strategy_direction",
                "strategy_5scr_tradeplan_candidates_v2.material_context_hash",
                "strategy_5scr_tradeplan_candidates_v2.thesis_semantic_identity_hash",
                "strategy_5scr_tradeplan_candidates_v2.candidate_sequence",
                "strategy_5scr_tradeplan_candidates_v2.candidate_revision",
                "strategy_5scr_tradeplan_candidates_v2.material_candidate_hash",
            ],
            name="fk_5scr_tradeplan_candidate_evaluation_v2_candidate_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "evaluation_sequence",
            name="uq_5scr_tradeplan_candidate_evaluation_v2_sequence",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "evaluated_at",
            name="uq_5scr_tradeplan_candidate_evaluation_v2_clock",
        ),
        sa.CheckConstraint(
            "evaluation_id ~ '^5scr-tradeplan-eval:[0-9a-f]{32}$' AND "
            "material_box_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "material_context_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "thesis_semantic_identity_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "execution_box_freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "material_evaluation_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_tradeplan_candidate_evaluation_v2_identity",
        ),
        sa.CheckConstraint(
            "evaluation_sequence >= 1 AND strategy_direction IN ('BUY','SELL') "
            "AND decision IN ('CANDIDATE','WAIT','NO_TRADE')",
            name="ck_5scr_tradeplan_candidate_evaluation_v2_decision",
        ),
        sa.CheckConstraint(
            "((decision = 'CANDIDATE' AND tradeplan_id IS NOT NULL "
            "AND candidate_sequence IS NOT NULL AND candidate_revision IS NOT NULL "
            "AND material_candidate_hash ~ '^sha256:[0-9a-f]{64}$') OR "
            "(decision IN ('WAIT','NO_TRADE') AND tradeplan_id IS NULL "
            "AND candidate_sequence IS NULL AND candidate_revision IS NULL "
            "AND material_candidate_hash IS NULL))",
            name="ck_5scr_tradeplan_candidate_evaluation_v2_candidate_link",
        ),
        sa.CheckConstraint(
            "length(reason_code) >= 3 AND jsonb_typeof(reason_codes) = 'array' "
            "AND jsonb_array_length(reason_codes) > 0 AND jsonb_typeof(evidence_payload) = 'object' "
            "AND jsonb_typeof(target_authority_payload) = 'object' "
            "AND jsonb_typeof(stop_authority_payload) = 'object'",
            name="ck_5scr_tradeplan_candidate_evaluation_v2_payloads",
        ),
        sa.CheckConstraint(
            "valid_for_execution IS FALSE AND execution_authority IS FALSE",
            name="ck_5scr_tradeplan_candidate_evaluation_v2_shadow_only",
        ),
    )
    op.create_unique_constraint(
        "uq_5scr_tradeplan_candidate_evaluation_v2_request",
        "strategy_5scr_tradeplan_candidate_evaluations_v2",
        ["execution_box_id", "source_request_id"],
    )
    op.create_index(
        "ix_5scr_tradeplan_candidate_evaluation_v2_history",
        "strategy_5scr_tradeplan_candidate_evaluations_v2",
        ["execution_box_id", "evaluation_sequence", "evaluation_id"],
    )
    op.create_index(
        "ix_5scr_tradeplan_candidate_evaluation_v2_candidate",
        "strategy_5scr_tradeplan_candidate_evaluations_v2",
        ["tradeplan_id", "evaluation_sequence"],
        postgresql_where=sa.text("tradeplan_id IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION strategy_5scr_guard_tradeplan_candidate_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_DELETE_FORBIDDEN'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_tradeplan_candidate_v2_immutable';
            END IF;
            IF ROW(
                NEW.tradeplan_id, NEW.strategy_lifecycle_id, NEW.context_epoch_id,
                NEW.strategy_thesis_id, NEW.execution_box_id,
                NEW.candidate_sequence, NEW.candidate_revision,
                NEW.previous_tradeplan_id, NEW.previous_candidate_sequence,
                NEW.previous_candidate_revision, NEW.symbol, NEW.strategy_direction,
                NEW.candidate_status, NEW.route_type, NEW.candidate_price, NEW.stop_loss, NEW.target_price,
                NEW.risk_distance_price, NEW.target_distance_price, NEW.rr, NEW.pip_size,
                NEW.target_mode, NEW.broker_authority_hash, NEW.broker_geometry_material_hash,
                NEW.broker_digits, NEW.broker_point, NEW.broker_tick_size, NEW.broker_pip_size,
                NEW.broker_spread_price, NEW.material_box_hash, NEW.execution_box_freeze_authority_hash,
                NEW.material_context_hash, NEW.thesis_semantic_identity_hash, NEW.box_sequence, NEW.box_version,
                NEW.structural_target_authority_hash, NEW.structural_target_material_hash,
                NEW.target_map_authority_hash, NEW.structural_stop_authority_hash,
                NEW.material_candidate_hash, NEW.formation_evidence_hash, NEW.source_candle_ids,
                NEW.opened_at, NEW.rule_version, NEW.valid_for_execution,
                NEW.execution_authority, NEW.next_required_stage, NEW.payload,
                NEW.target_authority_payload, NEW.stop_authority_payload, NEW.evidence_payload,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tradeplan_id, OLD.strategy_lifecycle_id, OLD.context_epoch_id,
                OLD.strategy_thesis_id, OLD.execution_box_id,
                OLD.candidate_sequence, OLD.candidate_revision,
                OLD.previous_tradeplan_id, OLD.previous_candidate_sequence,
                OLD.previous_candidate_revision, OLD.symbol, OLD.strategy_direction,
                OLD.candidate_status, OLD.route_type, OLD.candidate_price, OLD.stop_loss, OLD.target_price,
                OLD.risk_distance_price, OLD.target_distance_price, OLD.rr, OLD.pip_size,
                OLD.target_mode, OLD.broker_authority_hash, OLD.broker_geometry_material_hash,
                OLD.broker_digits, OLD.broker_point, OLD.broker_tick_size, OLD.broker_pip_size,
                OLD.broker_spread_price, OLD.material_box_hash, OLD.execution_box_freeze_authority_hash,
                OLD.material_context_hash, OLD.thesis_semantic_identity_hash, OLD.box_sequence, OLD.box_version,
                OLD.structural_target_authority_hash, OLD.structural_target_material_hash,
                OLD.target_map_authority_hash, OLD.structural_stop_authority_hash,
                OLD.material_candidate_hash, OLD.formation_evidence_hash, OLD.source_candle_ids,
                OLD.opened_at, OLD.rule_version, OLD.valid_for_execution,
                OLD.execution_authority, OLD.next_required_stage, OLD.payload,
                OLD.target_authority_payload, OLD.stop_authority_payload, OLD.evidence_payload,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_MATERIAL_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_tradeplan_candidate_v2_immutable';
            END IF;
            IF OLD.lifecycle_state <> 'ACTIVE' OR
               NEW.lifecycle_state NOT IN ('SUPERSEDED','INVALIDATED','EXPIRED') OR
               NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_TRANSITION_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_tradeplan_candidate_v2_transition';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_5scr_tradeplan_candidates_v2_guard
        BEFORE UPDATE OR DELETE ON strategy_5scr_tradeplan_candidates_v2
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_tradeplan_candidate_v2()
        """
    )
    op.execute(
        """
        CREATE FUNCTION strategy_5scr_reject_tradeplan_candidate_evaluation_v2_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'STRATEGY_5SCR_TRADEPLAN_CANDIDATE_EVALUATION_V2_IMMUTABLE'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_5scr_tradeplan_candidate_evaluation_v2_immutable';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_5scr_tradeplan_candidate_evaluations_v2_immutable
        BEFORE UPDATE OR DELETE ON strategy_5scr_tradeplan_candidate_evaluations_v2
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_reject_tradeplan_candidate_evaluation_v2_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_strategy_5scr_tradeplan_candidate_evaluations_v2_immutable "
        "ON strategy_5scr_tradeplan_candidate_evaluations_v2"
    )
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_reject_tradeplan_candidate_evaluation_v2_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_strategy_5scr_tradeplan_candidates_v2_guard "
        "ON strategy_5scr_tradeplan_candidates_v2"
    )
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_guard_tradeplan_candidate_v2()")
    op.drop_index(
        "ix_5scr_tradeplan_candidate_evaluation_v2_candidate",
        table_name="strategy_5scr_tradeplan_candidate_evaluations_v2",
    )
    op.drop_index(
        "ix_5scr_tradeplan_candidate_evaluation_v2_history",
        table_name="strategy_5scr_tradeplan_candidate_evaluations_v2",
    )
    op.drop_constraint(
        "uq_5scr_tradeplan_candidate_evaluation_v2_request",
        "strategy_5scr_tradeplan_candidate_evaluations_v2",
        type_="unique",
    )
    op.drop_table("strategy_5scr_tradeplan_candidate_evaluations_v2")
    op.drop_index(
        "ix_5scr_tradeplan_candidate_v2_lifecycle_history",
        table_name="strategy_5scr_tradeplan_candidates_v2",
    )
    op.drop_index(
        "uq_5scr_tradeplan_candidate_v2_active_lifecycle",
        table_name="strategy_5scr_tradeplan_candidates_v2",
    )
    op.drop_index(
        "uq_5scr_tradeplan_candidate_v2_active_box",
        table_name="strategy_5scr_tradeplan_candidates_v2",
    )
    op.drop_table("strategy_5scr_tradeplan_candidates_v2")
    op.drop_constraint(
        "uq_5scr_execution_box_tradeplan_evaluation_scope_v1",
        "strategy_5scr_execution_boxes_v1",
        type_="unique",
    )
    op.drop_constraint(
        "uq_5scr_execution_box_tradeplan_scope_v1",
        "strategy_5scr_execution_boxes_v1",
        type_="unique",
    )
    op.drop_constraint(
        "uq_5scr_thesis_tradeplan_scope_v1",
        "strategy_5scr_directional_theses_v1",
        type_="unique",
    )
    op.drop_constraint(
        "uq_5scr_context_epoch_tradeplan_scope_v1",
        "strategy_5scr_context_epochs_v1",
        type_="unique",
    )
