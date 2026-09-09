"""Add durable, versioned, shadow-only ExecutionBox V1.

Revision ID: 20260812_03
Revises: 20260812_02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260812_03"
down_revision = "20260812_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_5scr_thesis_execution_box_scope_v1",
        "strategy_5scr_directional_theses_v1",
        [
            "strategy_thesis_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "symbol",
            "strategy_direction",
        ],
    )
    op.create_table(
        "strategy_5scr_execution_boxes_v1",
        sa.Column("execution_box_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("box_sequence", sa.Integer(), nullable=False),
        sa.Column("box_version", sa.Integer(), nullable=False),
        sa.Column("previous_execution_box_id", sa.Text(), nullable=True),
        sa.Column("previous_box_sequence", sa.Integer(), nullable=True),
        sa.Column("previous_box_version", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("route_type", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("box_low", sa.Float(), nullable=False),
        sa.Column("box_high", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freeze_authority_hash", sa.String(length=71), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("material_box_hash", sa.String(length=71), nullable=False),
        sa.Column("formation_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("thesis_semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("source_m1_ids", JSONB(), nullable=False),
        sa.Column("source_m1_evidence_ids", JSONB(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_source_request_id", sa.Text(), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        # The formation evidence is immutable.  The latest accepted observation
        # advances independently so restart ordering never depends on process
        # memory and the original material authority is never overwritten.
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("latest_evidence_payload", JSONB(), nullable=False),
        sa.Column("freeze_evidence_payload", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_execution_box_lifecycle_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_epoch_id", "strategy_lifecycle_id", "symbol"],
            [
                "strategy_5scr_context_epochs_v1.context_epoch_id",
                "strategy_5scr_context_epochs_v1.strategy_lifecycle_id",
                "strategy_5scr_context_epochs_v1.symbol",
            ],
            name="fk_5scr_execution_box_context_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "strategy_thesis_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "symbol",
                "strategy_direction",
            ],
            [
                "strategy_5scr_directional_theses_v1.strategy_thesis_id",
                "strategy_5scr_directional_theses_v1.strategy_lifecycle_id",
                "strategy_5scr_directional_theses_v1.context_epoch_id",
                "strategy_5scr_directional_theses_v1.symbol",
                "strategy_5scr_directional_theses_v1.strategy_direction",
            ],
            name="fk_5scr_execution_box_thesis_scope_v1",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "previous_execution_box_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "symbol",
                "strategy_direction",
                "previous_box_sequence",
                "previous_box_version",
            ],
            [
                "strategy_5scr_execution_boxes_v1.execution_box_id",
                "strategy_5scr_execution_boxes_v1.strategy_lifecycle_id",
                "strategy_5scr_execution_boxes_v1.context_epoch_id",
                "strategy_5scr_execution_boxes_v1.strategy_thesis_id",
                "strategy_5scr_execution_boxes_v1.symbol",
                "strategy_5scr_execution_boxes_v1.strategy_direction",
                "strategy_5scr_execution_boxes_v1.box_sequence",
                "strategy_5scr_execution_boxes_v1.box_version",
            ],
            name="fk_5scr_execution_box_previous_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "symbol",
            "strategy_direction",
            "box_sequence",
            "box_version",
            name="uq_5scr_execution_box_predecessor_scope_v1",
        ),
        sa.UniqueConstraint(
            "execution_box_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "symbol",
            "material_box_hash",
            name="uq_5scr_execution_box_observation_scope_v1",
        ),
        sa.UniqueConstraint(
            "strategy_thesis_id",
            "box_version",
            name="uq_5scr_execution_box_version_v1",
        ),
        sa.UniqueConstraint(
            "strategy_lifecycle_id",
            "box_sequence",
            name="uq_5scr_execution_box_sequence_v1",
        ),
        sa.CheckConstraint(
            "execution_box_id ~ '^5scr-execution-box:[0-9a-f]{32}$' "
            "AND material_box_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND formation_evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND thesis_semantic_identity_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_execution_box_identity_v1",
        ),
        sa.CheckConstraint(
            "box_sequence >= 1 AND box_version >= 1 AND state_version >= 1 AND box_high > box_low",
            name="ck_5scr_execution_box_geometry_v1",
        ),
        sa.CheckConstraint(
            "strategy_direction IN ('BUY','SELL') AND "
            "state IN ('BUILDING','FROZEN','SUPERSEDED','INVALIDATED','CONSUMED','EXPIRED')",
            name="ck_5scr_execution_box_state_v1",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_m1_ids) = 'array' AND jsonb_array_length(source_m1_ids) > 0 "
            "AND jsonb_typeof(source_m1_evidence_ids) = 'array' "
            "AND jsonb_array_length(source_m1_evidence_ids) > 0",
            name="ck_5scr_execution_box_sources_v1",
        ),
        sa.CheckConstraint(
            "((box_version = 1 AND previous_execution_box_id IS NULL "
            "AND previous_box_sequence IS NULL AND previous_box_version IS NULL) OR "
            "(box_version > 1 AND previous_execution_box_id IS NOT NULL "
            "AND previous_box_sequence = box_sequence - 1 "
            "AND previous_box_version = box_version - 1))",
            name="ck_5scr_execution_box_lineage_v1",
        ),
        sa.CheckConstraint(
            "(state = 'BUILDING' AND frozen_at IS NULL AND superseded_at IS NULL "
            "AND freeze_authority_hash IS NULL AND freeze_evidence_payload IS NULL "
            "AND invalidated_at IS NULL AND consumed_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'FROZEN' AND frozen_at >= opened_at "
            "AND freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND freeze_evidence_payload IS NOT NULL AND superseded_at IS NULL "
            "AND invalidated_at IS NULL AND consumed_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'SUPERSEDED' AND frozen_at IS NULL AND freeze_authority_hash IS NULL "
            "AND freeze_evidence_payload IS NULL "
            "AND superseded_at >= opened_at AND invalidated_at IS NULL "
            "AND consumed_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'INVALIDATED' AND ((frozen_at IS NULL AND freeze_authority_hash IS NULL "
            "AND freeze_evidence_payload IS NULL) OR "
            "(frozen_at >= opened_at AND freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND freeze_evidence_payload IS NOT NULL)) "
            "AND invalidated_at >= opened_at AND superseded_at IS NULL "
            "AND consumed_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'CONSUMED' AND frozen_at >= opened_at "
            "AND freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND freeze_evidence_payload IS NOT NULL "
            "AND consumed_at >= opened_at AND superseded_at IS NULL "
            "AND invalidated_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'EXPIRED' AND ((frozen_at IS NULL AND freeze_authority_hash IS NULL "
            "AND freeze_evidence_payload IS NULL) OR "
            "(frozen_at >= opened_at AND freeze_authority_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND freeze_evidence_payload IS NOT NULL)) "
            "AND expired_at >= opened_at AND superseded_at IS NULL "
            "AND invalidated_at IS NULL AND consumed_at IS NULL)",
            name="ck_5scr_execution_box_temporal_v1",
        ),
        sa.CheckConstraint(
            "valid_for_execution IS FALSE AND execution_authority IS FALSE",
            name="ck_5scr_execution_box_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_execution_box_active_thesis_v1",
        "strategy_5scr_execution_boxes_v1",
        ["strategy_thesis_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('BUILDING','FROZEN')"),
    )
    op.create_index(
        "uq_5scr_execution_box_active_lifecycle_v1",
        "strategy_5scr_execution_boxes_v1",
        ["strategy_lifecycle_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('BUILDING','FROZEN')"),
    )
    op.create_index(
        "ix_5scr_execution_box_lifecycle_history_v1",
        "strategy_5scr_execution_boxes_v1",
        ["strategy_lifecycle_id", "box_sequence", "execution_box_id"],
    )

    op.create_table(
        "strategy_5scr_execution_box_observations_v1",
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("execution_box_id", sa.Text(), nullable=False),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_request_id", sa.Text(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("material_box_hash", sa.String(length=71), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("evidence_payload", JSONB(), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            [
                "execution_box_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "symbol",
                "material_box_hash",
            ],
            [
                "strategy_5scr_execution_boxes_v1.execution_box_id",
                "strategy_5scr_execution_boxes_v1.strategy_lifecycle_id",
                "strategy_5scr_execution_boxes_v1.context_epoch_id",
                "strategy_5scr_execution_boxes_v1.strategy_thesis_id",
                "strategy_5scr_execution_boxes_v1.symbol",
                "strategy_5scr_execution_boxes_v1.material_box_hash",
            ],
            name="fk_5scr_execution_box_observation_box_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "strategy_thesis_id",
            "observed_at",
            name="uq_5scr_execution_box_observation_clock_v1",
        ),
        sa.CheckConstraint(
            "observation_id ~ '^5scr-execution-box-observation:[0-9a-f]{32}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND material_box_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_execution_box_observation_identity_v1",
        ),
        sa.CheckConstraint(
            "outcome IN ('OPENED','DUPLICATE','NO_CHANGE','FROZEN','SUPERSEDED')",
            name="ck_5scr_execution_box_observation_outcome_v1",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE",
            name="ck_5scr_execution_box_observation_shadow_only_v1",
        ),
    )
    op.create_index(
        "uq_5scr_execution_box_observation_request_v1",
        "strategy_5scr_execution_box_observations_v1",
        ["strategy_thesis_id", "source_request_id"],
        unique=True,
        postgresql_where=sa.text("source_request_id IS NOT NULL"),
    )
    op.create_index(
        "ix_5scr_execution_box_observation_history_v1",
        "strategy_5scr_execution_box_observations_v1",
        ["strategy_thesis_id", "observed_at", "observation_id"],
    )

    # The observation ledger is append-only authority evidence, not telemetry
    # that may be rewritten after a restart.
    op.execute(
        """
        CREATE FUNCTION strategy_5scr_reject_execution_box_observation_mutation_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_OBSERVATION_IMMUTABLE'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_observation_immutable_v1';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_5scr_execution_box_observations_v1_immutable
        BEFORE UPDATE OR DELETE ON strategy_5scr_execution_box_observations_v1
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_reject_execution_box_observation_mutation_v1()
        """
    )

    op.execute(
        """
        CREATE FUNCTION strategy_5scr_guard_execution_box_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_DELETE_FORBIDDEN'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_immutable_v1';
            END IF;
            IF ROW(
                NEW.execution_box_id, NEW.strategy_lifecycle_id, NEW.context_epoch_id,
                NEW.strategy_thesis_id, NEW.box_sequence, NEW.box_version,
                NEW.previous_execution_box_id, NEW.previous_box_sequence, NEW.previous_box_version,
                NEW.symbol, NEW.strategy_direction,
                NEW.route_type, NEW.box_low, NEW.box_high, NEW.opened_at,
                NEW.material_box_hash, NEW.formation_evidence_hash, NEW.thesis_semantic_identity_hash,
                NEW.source_m1_ids, NEW.rule_version,
                NEW.valid_for_execution, NEW.execution_authority
            ) IS DISTINCT FROM ROW(
                OLD.execution_box_id, OLD.strategy_lifecycle_id, OLD.context_epoch_id,
                OLD.strategy_thesis_id, OLD.box_sequence, OLD.box_version,
                OLD.previous_execution_box_id, OLD.previous_box_sequence, OLD.previous_box_version,
                OLD.symbol, OLD.strategy_direction,
                OLD.route_type, OLD.box_low, OLD.box_high, OLD.opened_at,
                OLD.material_box_hash, OLD.formation_evidence_hash, OLD.thesis_semantic_identity_hash,
                OLD.source_m1_ids, OLD.rule_version,
                OLD.valid_for_execution, OLD.execution_authority
            ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_GEOMETRY_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_immutable_v1';
            END IF;
            IF NEW.evidence_payload IS DISTINCT FROM OLD.evidence_payload OR
               (NEW.payload - 'state' - 'frozen_at_utc' - 'superseded_at_utc'
                    - 'freeze_authority_hash' - 'invalidated_at_utc' - 'consumed_at_utc' - 'expired_at_utc'
                    - 'evidence_hash' - 'source_m1_evidence_ids'
                    - 'last_observed_at_utc' - 'last_source_request_id' - 'state_version')
               IS DISTINCT FROM
               (OLD.payload - 'state' - 'frozen_at_utc' - 'superseded_at_utc'
                    - 'freeze_authority_hash' - 'invalidated_at_utc' - 'consumed_at_utc' - 'expired_at_utc'
                    - 'evidence_hash' - 'source_m1_evidence_ids'
                    - 'last_observed_at_utc' - 'last_source_request_id' - 'state_version') THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_PAYLOAD_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_immutable_v1';
            END IF;
            IF NOT (
                NEW.freeze_evidence_payload IS NOT DISTINCT FROM OLD.freeze_evidence_payload OR
                (OLD.state = 'BUILDING' AND NEW.state = 'FROZEN'
                 AND OLD.freeze_evidence_payload IS NULL AND NEW.freeze_evidence_payload IS NOT NULL)
            ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_FREEZE_EVIDENCE_IMMUTABLE'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_immutable_v1';
            END IF;
            IF ROW(NEW.evidence_hash, NEW.source_m1_evidence_ids, NEW.latest_evidence_payload)
               IS DISTINCT FROM
               ROW(OLD.evidence_hash, OLD.source_m1_evidence_ids, OLD.latest_evidence_payload)
               AND NOT (
                    (OLD.state = 'BUILDING' AND NEW.state = 'FROZEN') OR
                    (OLD.state = NEW.state AND OLD.state IN ('BUILDING','FROZEN')
                     AND NEW.last_observed_at > OLD.last_observed_at)
               ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_EVIDENCE_CURSOR_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_transition_v1';
            END IF;
            IF NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_VERSION_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_transition_v1';
            END IF;
            IF NEW.last_observed_at < OLD.last_observed_at THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_CURSOR_REGRESSION'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_transition_v1';
            END IF;
            IF NOT (
                (OLD.state = 'BUILDING' AND NEW.state IN ('FROZEN','SUPERSEDED','INVALIDATED','EXPIRED')) OR
                (OLD.state = 'FROZEN' AND NEW.state IN ('INVALIDATED','CONSUMED','EXPIRED')) OR
                (OLD.state = NEW.state AND OLD.state IN ('BUILDING','FROZEN')
                 AND NEW.last_observed_at > OLD.last_observed_at
                 AND NEW.evidence_hash IS DISTINCT FROM OLD.evidence_hash
                 AND NEW.latest_evidence_payload IS DISTINCT FROM OLD.latest_evidence_payload)
            ) THEN
                RAISE EXCEPTION 'STRATEGY_5SCR_EXECUTION_BOX_TRANSITION_INVALID'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_execution_box_transition_v1';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard
        BEFORE UPDATE OR DELETE ON strategy_5scr_execution_boxes_v1
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_execution_box_v1()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_strategy_5scr_execution_box_observations_v1_immutable "
        "ON strategy_5scr_execution_box_observations_v1"
    )
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_reject_execution_box_observation_mutation_v1()")
    op.drop_index(
        "ix_5scr_execution_box_observation_history_v1",
        table_name="strategy_5scr_execution_box_observations_v1",
    )
    op.drop_index(
        "uq_5scr_execution_box_observation_request_v1",
        table_name="strategy_5scr_execution_box_observations_v1",
    )
    op.drop_table("strategy_5scr_execution_box_observations_v1")
    op.execute("DROP TRIGGER IF EXISTS trg_strategy_5scr_execution_boxes_v1_guard ON strategy_5scr_execution_boxes_v1")
    op.execute("DROP FUNCTION IF EXISTS strategy_5scr_guard_execution_box_v1()")
    op.drop_index(
        "ix_5scr_execution_box_lifecycle_history_v1",
        table_name="strategy_5scr_execution_boxes_v1",
    )
    op.drop_index(
        "uq_5scr_execution_box_active_lifecycle_v1",
        table_name="strategy_5scr_execution_boxes_v1",
    )
    op.drop_index(
        "uq_5scr_execution_box_active_thesis_v1",
        table_name="strategy_5scr_execution_boxes_v1",
    )
    op.drop_table("strategy_5scr_execution_boxes_v1")
    op.drop_constraint(
        "uq_5scr_thesis_execution_box_scope_v1",
        "strategy_5scr_directional_theses_v1",
        type_="unique",
    )
