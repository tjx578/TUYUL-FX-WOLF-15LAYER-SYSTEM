"""Add command-inert C2 SHADOW risk projections.

Revision ID: 20260813_03
Revises: 20260813_02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260813_03"
down_revision = "20260813_02"
branch_labels = None
depends_on = None

TABLE = "strategy_5scr_shadow_risk_projections_v1"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("shadow_authority_id", sa.Text(), nullable=False),
        sa.Column("source_admission_class", sa.String(length=80), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("execution_box_id", sa.Text(), nullable=False),
        sa.Column("candidate_sequence", sa.Integer(), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("thesis_semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("material_candidate_hash", sa.String(length=71), nullable=False),
        sa.Column("candidate_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("account_snapshot_hash", sa.String(length=71), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("stop_loss", sa.Numeric(28, 12), nullable=False),
        sa.Column("target_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("would_volume", sa.Numeric(28, 12), nullable=True),
        sa.Column("would_risk_usd", sa.Numeric(28, 12), nullable=True),
        sa.Column("would_margin_usd", sa.Numeric(28, 12), nullable=True),
        sa.Column("would_margin_status", sa.String(length=24), nullable=False),
        sa.Column("would_open_risk_after_usd", sa.Numeric(28, 12), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("kill_switch_observed", sa.String(length=16), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capital_reserved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("broker_side_effect_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order_send_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("shadow_authority_id", name="pk_5scr_shadow_risk_projection_v1"),
        sa.ForeignKeyConstraint(
            [
                "tradeplan_id",
                "strategy_lifecycle_id",
                "context_epoch_id",
                "strategy_thesis_id",
                "execution_box_id",
                "symbol",
                "direction",
                "material_context_hash",
                "thesis_semantic_identity_hash",
                "candidate_sequence",
                "candidate_revision",
                "material_candidate_hash",
                "candidate_evidence_hash",
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
                "strategy_5scr_tradeplan_candidates_v2.formation_evidence_hash",
            ],
            name="fk_5scr_shadow_risk_projection_v1_candidate_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_snapshot_id", "executor_id", "account_id"],
            [
                "executor_account_snapshots.snapshot_id",
                "executor_account_snapshots.executor_id",
                "executor_account_snapshots.account_id",
            ],
            name="fk_5scr_shadow_risk_projection_v1_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tradeplan_id",
            "candidate_sequence",
            "candidate_revision",
            "executor_id",
            "account_id",
            "account_snapshot_id",
            name="uq_5scr_shadow_risk_projection_v1_source",
        ),
        sa.CheckConstraint(
            "shadow_authority_id ~ '^5scr-shadow-authority-v1:[0-9a-f]{32}$' "
            "AND material_context_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND thesis_semantic_identity_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND material_candidate_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND candidate_evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND account_snapshot_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND authority_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_shadow_risk_projection_v1_identity",
        ),
        sa.CheckConstraint(
            "source_admission_class='CANONICAL_CANDIDATE_V2' "
            "AND rule_version='5scr.c2-shadow-risk-projection.v1' "
            "AND candidate_revision=1 AND candidate_sequence>=1",
            name="ck_5scr_shadow_risk_projection_v1_source",
        ),
        sa.CheckConstraint(
            "direction IN ('BUY','SELL') AND entry_price>0 AND stop_loss>0 AND target_price>0 "
            "AND ((direction='BUY' AND stop_loss<entry_price AND entry_price<target_price) "
            "OR (direction='SELL' AND target_price<entry_price AND entry_price<stop_loss))",
            name="ck_5scr_shadow_risk_projection_v1_geometry",
        ),
        sa.CheckConstraint(
            "would_margin_status='NOT_MEASURED' AND would_margin_usd IS NULL",
            name="ck_5scr_shadow_risk_projection_v1_margin_unknown",
        ),
        sa.CheckConstraint(
            "(decision='WOULD_RESERVE' AND state IN ('AVAILABLE','COMMAND_ISSUED') "
            "AND would_volume>0 AND would_risk_usd>0 AND would_open_risk_after_usd>=would_risk_usd) "
            "OR (decision='WOULD_REJECT' AND state='REJECTED' AND would_volume IS NULL "
            "AND would_risk_usd IS NULL AND would_open_risk_after_usd IS NULL)",
            name="ck_5scr_shadow_risk_projection_v1_decision",
        ),
        sa.CheckConstraint(
            "reason_code ~ '^[A-Z0-9_]{3,120}$' "
            "AND ((state IN ('AVAILABLE','REJECTED') AND state_version=1) "
            "OR (state='COMMAND_ISSUED' AND state_version=2)) "
            "AND projected_at<expires_at AND expires_at<=projected_at+INTERVAL '300 seconds'",
            name="ck_5scr_shadow_risk_projection_v1_lifecycle",
        ),
        sa.CheckConstraint(
            "kill_switch_observed='ENGAGED' AND execution_authority IS FALSE "
            "AND capital_reserved IS FALSE AND broker_side_effect_allowed IS FALSE "
            "AND order_send_eligible IS FALSE",
            name="ck_5scr_shadow_risk_projection_v1_inert",
        ),
    )
    op.create_index(
        "ix_5scr_shadow_risk_projection_v1_available",
        TABLE,
        ["state", "expires_at", "shadow_authority_id"],
    )
    op.create_index(
        "ix_5scr_shadow_risk_projection_v1_candidate",
        TABLE,
        ["tradeplan_id", "candidate_sequence", "candidate_revision"],
    )
    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_shadow_projection_transition_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'SHADOW projection rows are append-only'
                    USING ERRCODE='23514', CONSTRAINT='ck_5scr_shadow_risk_projection_v1_immutable';
            END IF;
            IF OLD.state='AVAILABLE' AND NEW.state='COMMAND_ISSUED'
               AND NEW.state_version=OLD.state_version+1
               AND (to_jsonb(NEW)-'state'-'state_version'-'updated_at')
                   = (to_jsonb(OLD)-'state'-'state_version'-'updated_at') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid SHADOW projection mutation'
                USING ERRCODE='23514', CONSTRAINT='ck_5scr_shadow_risk_projection_v1_transition';
        END $$;
        CREATE TRIGGER trg_5scr_guard_shadow_projection_transition_v1
        BEFORE UPDATE OR DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_shadow_projection_transition_v1();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER trg_5scr_guard_shadow_projection_transition_v1 ON {TABLE}")
    op.execute("DROP FUNCTION strategy_5scr_guard_shadow_projection_transition_v1()")
    op.drop_index("ix_5scr_shadow_risk_projection_v1_candidate", table_name=TABLE)
    op.drop_index("ix_5scr_shadow_risk_projection_v1_available", table_name=TABLE)
    op.drop_table(TABLE)
