"""Add Lifecycle V2 admission lineage and shadow evidence ownership.

Revision ID: 20260804_01
Revises: 20260803_04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260804_01"
down_revision = "20260803_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_lifecycle_admission_links_v2",
        sa.Column("admission_event_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("pressure_event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("raw_lineage_hash", sa.String(length=80), nullable=False),
        sa.Column("admission_rule_version", sa.String(length=100), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_admission_link_lifecycle_v2",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pressure_event_id"],
            ["strategy_5scr_lifecycle_event_links_v2.pressure_event_id"],
            name="fk_5scr_admission_link_event_v2",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "admission_event_id ~ '^5scr-admission:[0-9a-f]{32}$' AND raw_lineage_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_admission_link_identity_v2",
        ),
        sa.CheckConstraint("linked_at >= admitted_at", name="ck_5scr_admission_link_time_v2"),
        sa.CheckConstraint("execution_authority = false", name="ck_5scr_admission_link_shadow_only_v2"),
    )
    op.create_index(
        "ix_5scr_admission_links_lifecycle_v2",
        "strategy_5scr_lifecycle_admission_links_v2",
        ["strategy_lifecycle_id", "admitted_at"],
    )

    op.create_table(
        "strategy_5scr_evidence_jobs_v2",
        sa.Column("evidence_job_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False, unique=True),
        sa.Column("admission_event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("pressure_event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_evidence_job_lifecycle_v2",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admission_event_id"],
            ["strategy_5scr_lifecycle_admission_links_v2.admission_event_id"],
            name="fk_5scr_evidence_job_admission_v2",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "evidence_job_id ~ '^5scr-evidence-job-v2:[0-9a-f]{32}$'",
            name="ck_5scr_evidence_job_identity_v2",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','COMPLETED','FAILED')",
            name="ck_5scr_evidence_job_status_v2",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_5scr_evidence_job_attempts_v2"),
    )
    op.create_index(
        "ix_5scr_evidence_jobs_pending_v2",
        "strategy_5scr_evidence_jobs_v2",
        ["created_at", "evidence_job_id"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "strategy_5scr_evidence_snapshots_v2",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column("evidence_job_id", sa.Text(), nullable=False, unique=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False, unique=True),
        sa.Column("admission_event_id", sa.Text(), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_calendar_version", sa.String(length=120), nullable=False),
        sa.Column("source_candle_ids", JSONB(), nullable=False),
        sa.Column("max_source_candle_close", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_candles_closed", sa.Boolean(), nullable=False),
        sa.Column("coverage_status", sa.String(length=20), nullable=False),
        sa.Column("context_hash", sa.String(length=80), nullable=False),
        sa.Column("evidence_hash", sa.String(length=80), nullable=False),
        sa.Column("result_state", sa.String(length=20), nullable=False),
        sa.Column("terminal_reason", sa.String(length=160), nullable=False),
        sa.Column("trade_geometry_hash", sa.String(length=80), nullable=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["evidence_job_id"],
            ["strategy_5scr_evidence_jobs_v2.evidence_job_id"],
            name="fk_5scr_evidence_snapshot_job_v2",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_lifecycle_id"],
            ["strategy_5scr_analysis_lifecycles_v2.strategy_lifecycle_id"],
            name="fk_5scr_evidence_snapshot_lifecycle_v2",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "snapshot_id ~ '^5scr-evidence-v2:[0-9a-f]{32}$' "
            "AND context_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND (trade_geometry_hash IS NULL OR trade_geometry_hash ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_5scr_evidence_snapshot_identity_v2",
        ),
        sa.CheckConstraint(
            "coverage_status IN ('COMPLETE','INCOMPLETE') AND result_state IN ('WAIT','NO_TRADE','CONDITIONAL')",
            name="ck_5scr_evidence_snapshot_result_v2",
        ),
        sa.CheckConstraint(
            "all_candles_closed = true "
            "AND (max_source_candle_close IS NULL OR max_source_candle_close <= decision_time)",
            name="ck_5scr_evidence_snapshot_asof_v2",
        ),
        sa.CheckConstraint(
            "valid_for_execution = false AND execution_authority = false",
            name="ck_5scr_evidence_snapshot_shadow_only_v2",
        ),
    )
    op.create_index(
        "ix_5scr_evidence_snapshots_decision_v2",
        "strategy_5scr_evidence_snapshots_v2",
        ["decision_time", "strategy_lifecycle_id"],
    )

    op.create_table(
        "strategy_5scr_evidence_comparisons_v2",
        sa.Column("comparison_id", sa.Text(), primary_key=True),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False, unique=True),
        sa.Column("v2_snapshot_id", sa.Text(), nullable=False, unique=True),
        sa.Column("legacy_lifecycle_id", sa.Text(), nullable=True),
        sa.Column("legacy_snapshot_id", sa.String(length=80), nullable=True),
        sa.Column("same_lifecycle_grouping", sa.Boolean(), nullable=True),
        sa.Column("same_candle_set", sa.Boolean(), nullable=True),
        sa.Column("same_context_hash", sa.Boolean(), nullable=True),
        sa.Column("same_terminal_reason", sa.Boolean(), nullable=True),
        sa.Column("same_trade_geometry", sa.Boolean(), nullable=True),
        sa.Column("reason_codes", JSONB(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["v2_snapshot_id"],
            ["strategy_5scr_evidence_snapshots_v2.snapshot_id"],
            name="fk_5scr_evidence_comparison_snapshot_v2",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "comparison_id ~ '^5scr-evidence-comparison-v2:[0-9a-f]{32}$'",
            name="ck_5scr_evidence_comparison_identity_v2",
        ),
        sa.CheckConstraint("execution_authority = false", name="ck_5scr_evidence_comparison_shadow_only_v2"),
    )


def downgrade() -> None:
    op.drop_table("strategy_5scr_evidence_comparisons_v2")
    op.drop_index("ix_5scr_evidence_snapshots_decision_v2", table_name="strategy_5scr_evidence_snapshots_v2")
    op.drop_table("strategy_5scr_evidence_snapshots_v2")
    op.drop_index("ix_5scr_evidence_jobs_pending_v2", table_name="strategy_5scr_evidence_jobs_v2")
    op.drop_table("strategy_5scr_evidence_jobs_v2")
    op.drop_index("ix_5scr_admission_links_lifecycle_v2", table_name="strategy_5scr_lifecycle_admission_links_v2")
    op.drop_table("strategy_5scr_lifecycle_admission_links_v2")
