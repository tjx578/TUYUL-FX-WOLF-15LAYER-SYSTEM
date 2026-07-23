"""Add immutable 5S-CR tradeplan candidates and M1 outcomes.

Revision ID: 20260724_04
Revises: 20260724_03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260724_04"
down_revision = "20260724_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_tradeplan_candidates",
        sa.Column("tradeplan_id", sa.String(length=80), primary_key=True),
        sa.Column("lifecycle_id", sa.Text(), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_snapshot_id", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["lifecycle_id"],
            ["strategy_5scr_lifecycles.lifecycle_id"],
            name="fk_5scr_candidate_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_snapshot_id"],
            ["strategy_5scr_evidence_snapshots.snapshot_id"],
            name="fk_5scr_candidate_evidence",
        ),
        sa.UniqueConstraint("event_id", name="uq_5scr_candidate_event"),
        sa.CheckConstraint("direction IN ('BUY', 'SELL')", name="ck_5scr_candidate_direction"),
    )
    op.create_index(
        "ix_5scr_candidates_symbol_decision",
        "strategy_5scr_tradeplan_candidates",
        ["symbol", "decision_at"],
    )

    op.create_table(
        "strategy_5scr_m1_outcomes",
        sa.Column("outcome_id", sa.String(length=80), primary_key=True),
        sa.Column("tradeplan_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evaluated_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tradeplan_id"],
            ["strategy_5scr_tradeplan_candidates.tradeplan_id"],
            name="fk_5scr_outcome_tradeplan",
        ),
        sa.UniqueConstraint("tradeplan_id", name="uq_5scr_outcome_tradeplan"),
        sa.CheckConstraint(
            "status IN ('TP1_FIRST', 'SL_FIRST', 'AMBIGUOUS_SAME_CANDLE', 'TIMEOUT', 'NO_DATA')",
            name="ck_5scr_outcome_status",
        ),
    )
    op.create_index(
        "ix_5scr_outcomes_status_created",
        "strategy_5scr_m1_outcomes",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_5scr_outcomes_status_created", table_name="strategy_5scr_m1_outcomes")
    op.drop_table("strategy_5scr_m1_outcomes")
    op.drop_index(
        "ix_5scr_candidates_symbol_decision",
        table_name="strategy_5scr_tradeplan_candidates",
    )
    op.drop_table("strategy_5scr_tradeplan_candidates")
