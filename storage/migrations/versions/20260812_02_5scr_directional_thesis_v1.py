"""Add immutable, shadow-only H1/M15 proofs and DirectionalThesis V1.

Revision ID: 20260812_02
Revises: 20260812_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260812_02"
down_revision = "20260812_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_5scr_context_epoch_scope_v1",
        "strategy_5scr_context_epochs_v1",
        ["context_epoch_id", "strategy_lifecycle_id", "symbol"],
    )

    op.create_table(
        "strategy_5scr_h1_structure_proofs_v1",
        sa.Column("h1_proof_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("structure_event", sa.String(length=20), nullable=False),
        sa.Column("anchor_candle_id", sa.String(length=71), nullable=False),
        sa.Column("confirmation_candle_id", sa.String(length=71), nullable=False),
        sa.Column("reference_level", sa.Float(), nullable=False),
        sa.Column("confirmation_close", sa.Float(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_candle_ids", JSONB(), nullable=False),
        sa.Column("source_content_hashes", JSONB(), nullable=False),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False),
        sa.Column("structural_authority", sa.Boolean(), nullable=False),
        sa.Column("material_proof_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("semantic_dedupe_key", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_h1_proof_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
            ],
            name="fk_5scr_h1_proof_context_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("semantic_dedupe_key", name="uq_5scr_h1_proof_semantic_v1"),
        sa.UniqueConstraint(
            "h1_proof_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "symbol",
            "strategy_direction",
            name="uq_5scr_h1_proof_scope_v1",
        ),
        sa.CheckConstraint(
            "h1_proof_id ~ '^5scr-h1-proof:[0-9a-f]{32}$' "
            "AND material_proof_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_h1_proof_identity_v1",
        ),
        sa.CheckConstraint("strategy_direction IN ('BUY','SELL')", name="ck_5scr_h1_proof_direction_v1"),
        sa.CheckConstraint(
            "structure_event IN ('BOS','CHOCH','CONTINUATION')",
            name="ck_5scr_h1_proof_event_v1",
        ),
        sa.CheckConstraint(
            "anchor_candle_id <> confirmation_candle_id AND reference_level > 0 AND confirmation_close > 0",
            name="ck_5scr_h1_proof_structure_v1",
        ),
        sa.CheckConstraint(
            "confirmed_at = coverage_end_at AND coverage_end_at <= decision_at AND coverage_start_at < confirmed_at",
            name="ck_5scr_h1_proof_order_v1",
        ),
        sa.CheckConstraint(
            "coverage_complete IS TRUE AND structural_authority IS TRUE",
            name="ck_5scr_h1_proof_authority_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_candle_ids) = 'array' AND jsonb_array_length(source_candle_ids) = 2 "
            "AND jsonb_typeof(source_content_hashes) = 'array' "
            "AND jsonb_array_length(source_content_hashes) = 2",
            name="ck_5scr_h1_proof_sources_v1",
        ),
        sa.CheckConstraint("execution_authority IS FALSE", name="ck_5scr_h1_proof_shadow_only_v1"),
    )
    op.create_index(
        "ix_5scr_h1_proof_context_time_v1",
        "strategy_5scr_h1_structure_proofs_v1",
        ["context_epoch_id", "confirmed_at", "h1_proof_id"],
    )

    op.create_table(
        "strategy_5scr_m15_structural_proofs_v1",
        sa.Column("m15_proof_id", sa.Text(), primary_key=True),
        sa.Column("h1_proof_id", sa.Text(), nullable=False),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("reference_candle_id", sa.String(length=71), nullable=False),
        sa.Column("break_candle_id", sa.String(length=71), nullable=False),
        sa.Column("completion_candle_id", sa.String(length=71), nullable=False),
        sa.Column("break_level", sa.Float(), nullable=False),
        sa.Column("h1_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("break_close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_kind", sa.String(length=24), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_candle_ids", JSONB(), nullable=False),
        sa.Column("source_content_hashes", JSONB(), nullable=False),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False),
        sa.Column("structural_authority", sa.Boolean(), nullable=False),
        sa.Column("ordering_valid", sa.Boolean(), nullable=False),
        sa.Column("material_proof_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("semantic_dedupe_key", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_m15_proof_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
            ],
            name="fk_5scr_m15_proof_context_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["h1_proof_id", "strategy_lifecycle_id", "context_epoch_id", "symbol", "strategy_direction"],
            [
                "strategy_5scr_h1_structure_proofs_v1.h1_proof_id",
                "strategy_5scr_h1_structure_proofs_v1.strategy_lifecycle_id",
                "strategy_5scr_h1_structure_proofs_v1.context_epoch_id",
                "strategy_5scr_h1_structure_proofs_v1.symbol",
                "strategy_5scr_h1_structure_proofs_v1.strategy_direction",
            ],
            name="fk_5scr_m15_proof_h1_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("semantic_dedupe_key", name="uq_5scr_m15_proof_semantic_v1"),
        sa.UniqueConstraint(
            "m15_proof_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "symbol",
            "strategy_direction",
            name="uq_5scr_m15_proof_scope_v1",
        ),
        sa.CheckConstraint(
            "m15_proof_id ~ '^5scr-m15-proof:[0-9a-f]{32}$' "
            "AND material_proof_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_m15_proof_identity_v1",
        ),
        sa.CheckConstraint("strategy_direction IN ('BUY','SELL')", name="ck_5scr_m15_proof_direction_v1"),
        sa.CheckConstraint(
            "completion_kind IN ('ACCEPTANCE','FAILED_RECLAIM','RETEST')",
            name="ck_5scr_m15_proof_completion_v1",
        ),
        sa.CheckConstraint(
            "h1_confirmed_at <= break_close_at AND break_close_at < completed_at "
            "AND completed_at = coverage_end_at AND coverage_start_at < break_close_at "
            "AND coverage_end_at <= decision_at",
            name="ck_5scr_m15_proof_order_v1",
        ),
        sa.CheckConstraint(
            "reference_candle_id <> break_candle_id AND break_candle_id <> completion_candle_id "
            "AND reference_candle_id <> completion_candle_id AND break_level > 0",
            name="ck_5scr_m15_proof_structure_v1",
        ),
        sa.CheckConstraint(
            "coverage_complete IS TRUE AND structural_authority IS TRUE AND ordering_valid IS TRUE",
            name="ck_5scr_m15_proof_authority_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_candle_ids) = 'array' AND jsonb_array_length(source_candle_ids) = 3 "
            "AND jsonb_typeof(source_content_hashes) = 'array' "
            "AND jsonb_array_length(source_content_hashes) = 3",
            name="ck_5scr_m15_proof_sources_v1",
        ),
        sa.CheckConstraint("execution_authority IS FALSE", name="ck_5scr_m15_proof_shadow_only_v1"),
    )
    op.create_index(
        "ix_5scr_m15_proof_context_time_v1",
        "strategy_5scr_m15_structural_proofs_v1",
        ["context_epoch_id", "completed_at", "m15_proof_id"],
    )

    op.create_table(
        "strategy_5scr_directional_theses_v1",
        sa.Column("strategy_thesis_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("thesis_sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("direction_immutable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("direction_domain_at_creation", sa.String(length=24), nullable=False),
        sa.Column("selected_route", sa.String(length=120), nullable=False),
        sa.Column("route_authorization_hash", sa.String(length=71), nullable=True),
        sa.Column("pressure_authority_mode", sa.String(length=40), nullable=False),
        sa.Column("pressure_contract_status", sa.String(length=24), nullable=False),
        sa.Column("pressure_reference_direction", sa.String(length=4), nullable=True),
        sa.Column("pressure_formal_transition_event_id", sa.String(length=240), nullable=True),
        sa.Column("pressure_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("counter_pressure_proof_hash", sa.String(length=71), nullable=True),
        sa.Column("h1_proof_id", sa.Text(), nullable=False),
        sa.Column("m15_proof_id", sa.Text(), nullable=False),
        sa.Column("structural_proof_hash", sa.String(length=71), nullable=False),
        sa.Column("semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("liveness_checked_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_reason", sa.String(length=160), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_thesis_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
            ],
            name="fk_5scr_thesis_context_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["h1_proof_id", "strategy_lifecycle_id", "context_epoch_id", "symbol", "strategy_direction"],
            [
                "strategy_5scr_h1_structure_proofs_v1.h1_proof_id",
                "strategy_5scr_h1_structure_proofs_v1.strategy_lifecycle_id",
                "strategy_5scr_h1_structure_proofs_v1.context_epoch_id",
                "strategy_5scr_h1_structure_proofs_v1.symbol",
                "strategy_5scr_h1_structure_proofs_v1.strategy_direction",
            ],
            name="fk_5scr_thesis_h1_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["m15_proof_id", "strategy_lifecycle_id", "context_epoch_id", "symbol", "strategy_direction"],
            [
                "strategy_5scr_m15_structural_proofs_v1.m15_proof_id",
                "strategy_5scr_m15_structural_proofs_v1.strategy_lifecycle_id",
                "strategy_5scr_m15_structural_proofs_v1.context_epoch_id",
                "strategy_5scr_m15_structural_proofs_v1.symbol",
                "strategy_5scr_m15_structural_proofs_v1.strategy_direction",
            ],
            name="fk_5scr_thesis_m15_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("strategy_lifecycle_id", "thesis_sequence", name="uq_5scr_thesis_sequence_v1"),
        sa.UniqueConstraint("semantic_identity_hash", name="uq_5scr_thesis_semantic_identity_v1"),
        sa.CheckConstraint(
            "strategy_thesis_id ~ '^5scr-thesis:[0-9a-f]{32}$' "
            "AND structural_proof_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND semantic_identity_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND pressure_authority_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_thesis_identity_v1",
        ),
        sa.CheckConstraint("strategy_direction IN ('BUY','SELL')", name="ck_5scr_thesis_direction_v1"),
        sa.CheckConstraint(
            "direction_domain_at_creation IN ('BUY_ONLY','SELL_ONLY','BOTH_CONDITIONAL','UNRESOLVED','EMPTY')",
            name="ck_5scr_thesis_domain_v1",
        ),
        sa.CheckConstraint(
            "(direction_domain_at_creation = 'BUY_ONLY' AND strategy_direction = 'BUY' "
            "AND route_authorization_hash IS NULL) OR "
            "(direction_domain_at_creation = 'SELL_ONLY' AND strategy_direction = 'SELL' "
            "AND route_authorization_hash IS NULL) OR "
            "(direction_domain_at_creation = 'BOTH_CONDITIONAL' AND route_authorization_hash IS NOT NULL)",
            name="ck_5scr_thesis_domain_direction_v1",
        ),
        sa.CheckConstraint(
            "pressure_authority_mode IN ('RADAR_ONLY','CONSOLIDATED_DIRECTION_CONTRACT') "
            "AND pressure_contract_status IN "
            "('RADAR_ONLY','LOCKED','UNRESOLVED','CONFLICT','EXPIRED','INVALIDATED','TRANSITION_PENDING')",
            name="ck_5scr_thesis_pressure_enum_v1",
        ),
        sa.CheckConstraint(
            "(pressure_authority_mode = 'RADAR_ONLY' AND pressure_contract_status = 'RADAR_ONLY' "
            "AND pressure_formal_transition_event_id IS NULL "
            "AND ((pressure_reference_direction IS NULL AND counter_pressure_proof_hash IS NULL) "
            "OR (pressure_reference_direction = strategy_direction AND counter_pressure_proof_hash IS NULL) "
            "OR (pressure_reference_direction <> strategy_direction "
            "AND counter_pressure_proof_hash IS NOT NULL))) OR "
            "(pressure_authority_mode = 'CONSOLIDATED_DIRECTION_CONTRACT' "
            "AND pressure_contract_status = 'LOCKED' "
            "AND pressure_formal_transition_event_id IS NOT NULL "
            "AND pressure_reference_direction = strategy_direction "
            "AND counter_pressure_proof_hash IS NULL)",
            name="ck_5scr_thesis_pressure_authority_v1",
        ),
        sa.CheckConstraint(
            "pressure_reference_direction IS NULL OR pressure_reference_direction IN ('BUY','SELL')",
            name="ck_5scr_thesis_pressure_direction_v1",
        ),
        sa.CheckConstraint(
            "route_authorization_hash IS NULL OR route_authorization_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_thesis_route_hash_v1",
        ),
        sa.CheckConstraint(
            "counter_pressure_proof_hash IS NULL OR counter_pressure_proof_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_thesis_counter_pressure_hash_v1",
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE','INVALIDATED','TERMINAL') AND state_version >= 1",
            name="ck_5scr_thesis_state_v1",
        ),
        sa.CheckConstraint(
            "liveness_checked_through >= created_at AND "
            "((state = 'ACTIVE' AND closed_at IS NULL AND closure_reason IS NULL) OR "
            "(state IN ('INVALIDATED','TERMINAL') AND closed_at >= liveness_checked_through "
            "AND closure_reason IS NOT NULL))",
            name="ck_5scr_thesis_temporal_v1",
        ),
        sa.CheckConstraint(
            "direction_immutable IS TRUE AND valid_for_execution IS FALSE AND execution_authority IS FALSE",
            name="ck_5scr_thesis_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_thesis_active_lifecycle_v1",
        "strategy_5scr_directional_theses_v1",
        ["strategy_lifecycle_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "ix_5scr_thesis_context_history_v1",
        "strategy_5scr_directional_theses_v1",
        ["context_epoch_id", "thesis_sequence", "strategy_thesis_id"],
    )

    op.execute(
        """
        CREATE FUNCTION strategy_5scr_reject_proof_mutation_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'STRATEGY_5SCR_PROOF_IMMUTABLE'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_proof_immutable_v1';
        END
        $$
        """
    )
    for table in ("strategy_5scr_h1_structure_proofs_v1", "strategy_5scr_m15_structural_proofs_v1"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION strategy_5scr_reject_proof_mutation_v1()
            """
        )

    op.execute(
        """
        CREATE FUNCTION strategy_5scr_guard_thesis_update_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_DELETE_FORBIDDEN'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_immutable_v1';
            END IF;
            IF ROW(
                NEW.strategy_thesis_id, NEW.strategy_lifecycle_id, NEW.context_epoch_id,
                NEW.thesis_sequence, NEW.symbol, NEW.strategy_direction,
                NEW.direction_immutable, NEW.direction_domain_at_creation,
                NEW.selected_route, NEW.route_authorization_hash,
                NEW.pressure_authority_mode, NEW.pressure_contract_status,
                NEW.pressure_reference_direction, NEW.pressure_formal_transition_event_id,
                NEW.pressure_authority_hash,
                NEW.counter_pressure_proof_hash, NEW.h1_proof_id, NEW.m15_proof_id,
                NEW.structural_proof_hash, NEW.semantic_identity_hash,
                NEW.rule_version, NEW.created_at, NEW.valid_for_execution,
                NEW.execution_authority
            ) IS DISTINCT FROM ROW(
                OLD.strategy_thesis_id, OLD.strategy_lifecycle_id, OLD.context_epoch_id,
                OLD.thesis_sequence, OLD.symbol, OLD.strategy_direction,
                OLD.direction_immutable, OLD.direction_domain_at_creation,
                OLD.selected_route, OLD.route_authorization_hash,
                OLD.pressure_authority_mode, OLD.pressure_contract_status,
                OLD.pressure_reference_direction, OLD.pressure_formal_transition_event_id,
                OLD.pressure_authority_hash,
                OLD.counter_pressure_proof_hash, OLD.h1_proof_id, OLD.m15_proof_id,
                OLD.structural_proof_hash, OLD.semantic_identity_hash,
                OLD.rule_version, OLD.created_at, OLD.valid_for_execution,
                OLD.execution_authority
            ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_IDENTITY_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_immutable_v1';
            END IF;
            IF (NEW.payload - 'state' - 'closed_at_utc' - 'closure_reason'
                    - 'state_version' - 'liveness_checked_through_utc')
               IS DISTINCT FROM
               (OLD.payload - 'state' - 'closed_at_utc' - 'closure_reason'
                    - 'state_version' - 'liveness_checked_through_utc') THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_PAYLOAD_IDENTITY_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_immutable_v1';
            END IF;
            IF OLD.state <> 'ACTIVE' OR NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_STATE_TRANSITION_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_transition_v1';
            END IF;
            IF NEW.state = 'ACTIVE' THEN
                IF NEW.closed_at IS NOT NULL OR NEW.closure_reason IS NOT NULL
                   OR NEW.liveness_checked_through <= OLD.liveness_checked_through THEN
                    RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_LIVENESS_TRANSITION_INVALID'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_transition_v1';
                END IF;
            ELSIF NEW.state IN ('INVALIDATED','TERMINAL') THEN
                IF NEW.closed_at IS NULL OR NEW.closure_reason IS NULL
                   OR NEW.liveness_checked_through < OLD.liveness_checked_through
                   OR NEW.liveness_checked_through > NEW.closed_at THEN
                    RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_STATE_TRANSITION_INVALID'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_transition_v1';
                END IF;
            ELSE
                RAISE EXCEPTION 'STRATEGY_5SCR_THESIS_STATE_TRANSITION_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_thesis_transition_v1';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_5scr_directional_theses_v1_guard
        BEFORE UPDATE OR DELETE ON strategy_5scr_directional_theses_v1
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_thesis_update_v1()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_strategy_5scr_directional_theses_v1_guard ON strategy_5scr_directional_theses_v1"
    )
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_guard_thesis_update_v1()")
    for table in ("strategy_5scr_m15_structural_proofs_v1", "strategy_5scr_h1_structure_proofs_v1"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_reject_proof_mutation_v1()")
    op.drop_index("ix_5scr_thesis_context_history_v1", table_name="strategy_5scr_directional_theses_v1")
    op.drop_index("uq_5scr_thesis_active_lifecycle_v1", table_name="strategy_5scr_directional_theses_v1")
    op.drop_table("strategy_5scr_directional_theses_v1")
    op.drop_index("ix_5scr_m15_proof_context_time_v1", table_name="strategy_5scr_m15_structural_proofs_v1")
    op.drop_table("strategy_5scr_m15_structural_proofs_v1")
    op.drop_index("ix_5scr_h1_proof_context_time_v1", table_name="strategy_5scr_h1_structure_proofs_v1")
    op.drop_table("strategy_5scr_h1_structure_proofs_v1")
    op.drop_constraint(
        "uq_5scr_context_epoch_scope_v1",
        "strategy_5scr_context_epochs_v1",
        type_="unique",
    )
