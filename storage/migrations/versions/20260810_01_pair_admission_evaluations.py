"""Add an independent durable PairAdmission evaluation ledger.

Revision ID: 20260810_01
Revises: 20260804_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260810_01"
down_revision = "20260804_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("pair_admission_evaluations"):
        op.create_table(
            "pair_admission_evaluations",
            sa.Column("evaluation_id", sa.Text(), primary_key=True),
            sa.Column("deployment_id", sa.String(200), nullable=False),
            sa.Column("raw_block_id", sa.Text(), nullable=False),
            sa.Column("rule_version", sa.String(100), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("direction", sa.String(4), nullable=True),
            sa.Column("evaluated_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_started_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_latest_event_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duration_seconds", sa.Float(), nullable=False),
            sa.Column("raw_event_count", sa.Integer(), nullable=False),
            sa.Column("effective_ticks", sa.Integer(), nullable=False),
            sa.Column("max_gap_seconds", sa.Float(), nullable=False),
            sa.Column("cross_symbol_interruption_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("raw_lineage_hash", sa.String(71), nullable=True),
            sa.Column("decision", sa.String(16), nullable=False),
            sa.Column("reason_code", sa.String(100), nullable=True),
            sa.Column("admission_event_id", sa.Text(), nullable=True),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("decision IN ('GRANTED', 'NOT_GRANTED')", name="ck_pair_admission_decision"),
            sa.CheckConstraint("direction IS NULL OR direction IN ('BUY', 'SELL')", name="ck_pair_admission_direction"),
            sa.CheckConstraint("duration_seconds >= 0", name="ck_pair_admission_duration_non_negative"),
            sa.CheckConstraint("raw_event_count >= 0", name="ck_pair_admission_event_count_non_negative"),
            sa.CheckConstraint("effective_ticks >= 0", name="ck_pair_admission_ticks_non_negative"),
            sa.CheckConstraint("max_gap_seconds >= 0", name="ck_pair_admission_gap_non_negative"),
            sa.CheckConstraint(
                "cross_symbol_interruption_count >= 0", name="ck_pair_admission_interruptions_non_negative"
            ),
            sa.CheckConstraint("execution_authority IS FALSE", name="ck_pair_admission_non_executable"),
            sa.CheckConstraint(
                "(decision = 'GRANTED' AND admission_event_id IS NOT NULL AND reason_code IS NULL) "
                "OR (decision = 'NOT_GRANTED' AND admission_event_id IS NULL AND reason_code IS NOT NULL)",
                name="ck_pair_admission_result_shape",
            ),
        )

    inspector = inspect(bind)
    indexes = {str(item["name"]) for item in inspector.get_indexes("pair_admission_evaluations")}
    if "ix_pair_admission_evaluated" not in indexes:
        op.create_index(
            "ix_pair_admission_evaluated",
            "pair_admission_evaluations",
            ["evaluated_at_utc", "decision"],
        )
    if "ix_pair_admission_symbol_block" not in indexes:
        op.create_index(
            "ix_pair_admission_symbol_block",
            "pair_admission_evaluations",
            ["deployment_id", "symbol", "raw_block_id"],
        )
    if "uq_pair_admission_one_grant_per_block" not in indexes:
        op.create_index(
            "uq_pair_admission_one_grant_per_block",
            "pair_admission_evaluations",
            ["deployment_id", "raw_block_id", "rule_version"],
            unique=True,
            postgresql_where=sa.text("decision = 'GRANTED'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("pair_admission_evaluations"):
        op.drop_table("pair_admission_evaluations")
