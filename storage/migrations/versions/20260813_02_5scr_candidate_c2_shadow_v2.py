"""Add CandidateV2 -> C2 SHADOW risk authority V2.

Revision ID: 20260813_02
Revises: 20260813_01

This authority is deliberately isolated from the legacy C2 tables.  It may
create backend strategy/risk authority and a dark final-signal outbox, but it
cannot create an execution command or broker authority.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260813_02"
down_revision = "20260813_01"
branch_labels = None
depends_on = None

HANDOFF = "strategy_5scr_candidate_c2_handoffs_v2"
EVALUATION = "strategy_5scr_candidate_c2_evaluations_v2"
RISK_LOCK = "strategy_5scr_campaign_risk_locks_v2"
RESERVATION = "strategy_5scr_risk_reservations_v2"
CAMPAIGN = "strategy_5scr_execution_campaigns_v2"
OUTBOX = "strategy_5scr_final_signal_outbox_v2"

_CANDIDATE_SCOPE = [
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
    "formation_evidence_hash",
]


def _candidate_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        _CANDIDATE_SCOPE,
        [f"strategy_5scr_tradeplan_candidates_v2.{item}" for item in _CANDIDATE_SCOPE],
        name=name,
        ondelete="RESTRICT",
    )


def _candidate_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("strategy_lifecycle_id", sa.Text(), nullable=False),
        sa.Column("context_epoch_id", sa.Text(), nullable=False),
        sa.Column("strategy_thesis_id", sa.Text(), nullable=False),
        sa.Column("execution_box_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_direction", sa.String(length=4), nullable=False),
        sa.Column("material_context_hash", sa.String(length=71), nullable=False),
        sa.Column("thesis_semantic_identity_hash", sa.String(length=71), nullable=False),
        sa.Column("candidate_sequence", sa.Integer(), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("material_candidate_hash", sa.String(length=71), nullable=False),
        sa.Column("formation_evidence_hash", sa.String(length=71), nullable=False),
    ]


def upgrade() -> None:
    # Bind P7 to an authenticated, immutable account-wide broker ledger
    # attestation. Missing fields on historical snapshots fail closed.
    op.add_column(
        "executor_account_snapshots",
        sa.Column(
            "broker_ledger_reconciled",
            sa.Boolean(),
            sa.Computed("COALESCE((payload ->> 'broker_ledger_reconciled')::boolean, false)", persisted=True),
            nullable=False,
        ),
    )
    op.add_column(
        "executor_account_snapshots",
        sa.Column(
            "pending_order_count",
            sa.Integer(),
            sa.Computed("jsonb_array_length(COALESCE(payload -> 'pending_orders', '[]'::jsonb))", persisted=True),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_executor_account_snapshot_c2_reconciliation_v2",
        "executor_account_snapshots",
        "pending_order_count >= 0",
    )
    op.create_unique_constraint(
        "uq_executor_account_snapshot_c2_scope_v2",
        "executor_account_snapshots",
        ["snapshot_id", "executor_id", "account_id"],
    )
    op.execute(
        """
        CREATE FUNCTION strategy_5scr_guard_account_snapshot_c2_update_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM strategy_5scr_candidate_c2_handoffs_v2 WHERE account_snapshot_id=OLD.snapshot_id)
               OR EXISTS (SELECT 1 FROM strategy_5scr_candidate_c2_evaluations_v2 WHERE account_snapshot_id=OLD.snapshot_id)
               OR EXISTS (SELECT 1 FROM strategy_5scr_campaign_risk_locks_v2 WHERE account_snapshot_id=OLD.snapshot_id)
               OR EXISTS (SELECT 1 FROM strategy_5scr_risk_reservations_v2 WHERE account_snapshot_id=OLD.snapshot_id)
               OR EXISTS (SELECT 1 FROM strategy_5scr_final_signal_outbox_v2 WHERE account_snapshot_id=OLD.snapshot_id) THEN
                RAISE EXCEPTION 'immutable admitted account reconciliation snapshot'
                    USING ERRCODE='23514', CONSTRAINT='ck_executor_account_snapshot_c2_reconciliation_v2';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_account_snapshot_c2_update_v2
        BEFORE UPDATE ON executor_account_snapshots
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_account_snapshot_c2_update_v2();
        """
    )

    op.create_unique_constraint(
        "uq_5scr_tradeplan_candidate_v2_c2_scope",
        "strategy_5scr_tradeplan_candidates_v2",
        _CANDIDATE_SCOPE,
    )

    op.create_table(
        HANDOFF,
        sa.Column("handoff_id", sa.Text(), nullable=False),
        *_candidate_columns(),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column(
            "account_snapshot_id",
            sa.String(length=200),
            sa.Computed("build_evidence_payload #>> '{account_snapshot,snapshot_id}'", persisted=True),
            nullable=False,
        ),
        sa.Column("account_snapshot_hash", sa.String(length=71), nullable=False),
        sa.Column("candidate_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("stop_loss", sa.Numeric(28, 12), nullable=False),
        sa.Column("take_profit", sa.Numeric(28, 12), nullable=False),
        sa.Column("target_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("stop_authority_hash", sa.String(length=71), nullable=False),
        sa.Column("broker_geometry_material_hash", sa.String(length=71), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("build_evidence_payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("handoff_id", name="pk_5scr_candidate_c2_handoff_v2"),
        _candidate_fk("fk_5scr_candidate_c2_handoff_v2_candidate_scope"),
        sa.ForeignKeyConstraint(
            ["account_snapshot_id", "executor_id", "account_id"],
            [
                "executor_account_snapshots.snapshot_id",
                "executor_account_snapshots.executor_id",
                "executor_account_snapshots.account_id",
            ],
            name="fk_5scr_candidate_c2_handoff_v2_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tradeplan_id", name="uq_5scr_candidate_c2_handoff_v2_candidate"),
        sa.UniqueConstraint(
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "account_snapshot_id",
            name="uq_5scr_candidate_c2_handoff_v2_risk_scope",
        ),
        sa.UniqueConstraint(
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "executor_id",
            "broker_server",
            "account_snapshot_id",
            "account_snapshot_hash",
            name="uq_5scr_candidate_c2_handoff_v2_outbox_scope",
        ),
        sa.CheckConstraint(
            "handoff_id ~ '^5scr-c2-handoff-v2:[0-9a-f]{32}$' AND "
            "authority_hash ~ '^sha256:[0-9a-f]{64}$' AND account_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_candidate_c2_handoff_v2_identity",
        ),
        sa.CheckConstraint(
            "strategy_direction IN ('BUY','SELL') AND candidate_sequence >= 1 AND candidate_revision = 1 "
            "AND candidate_price > 0 AND stop_loss > 0 AND take_profit > 0 AND "
            "((strategy_direction='BUY' AND stop_loss < candidate_price AND candidate_price < take_profit) OR "
            " (strategy_direction='SELL' AND take_profit < candidate_price AND candidate_price < stop_loss))",
            name="ck_5scr_candidate_c2_handoff_v2_geometry",
        ),
        sa.CheckConstraint(
            "execution_mode='SHADOW' AND execution_authority IS FALSE",
            name="ck_5scr_candidate_c2_handoff_v2_shadow",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload)='object' AND jsonb_typeof(build_evidence_payload)='object'",
            name="ck_5scr_candidate_c2_handoff_v2_payload",
        ),
    )
    op.create_index("ix_5scr_candidate_c2_handoff_v2_lifecycle", HANDOFF, ["strategy_lifecycle_id", "handoff_id"])
    op.create_index("ix_5scr_c2_handoff_v2_executor", HANDOFF, ["executor_id", "handoff_id"])
    op.create_index(
        "ix_5scr_c2_handoff_v2_snapshot_scope",
        HANDOFF,
        ["account_snapshot_id", "executor_id", "account_id"],
    )

    op.create_table(
        RISK_LOCK,
        sa.Column("risk_lock_id", sa.Text(), nullable=False),
        sa.Column("execution_campaign_id", sa.Text(), nullable=False),
        sa.Column("handoff_id", sa.Text(), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("balance_base", sa.Numeric(28, 12), nullable=False),
        sa.Column("risk_percent_per_entry", sa.Numeric(28, 12), nullable=False),
        sa.Column("risk_unit_usd", sa.Numeric(28, 12), nullable=False),
        sa.Column("max_campaign_risk_usd", sa.Numeric(28, 12), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("risk_authority", sa.Boolean(), nullable=False),
        sa.Column("broker_execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=120), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("risk_lock_id", name="pk_5scr_campaign_risk_lock_v2"),
        sa.UniqueConstraint(
            "execution_campaign_id",
            name="uq_5scr_campaign_risk_lock_v2_campaign",
        ),
        sa.UniqueConstraint("handoff_id", name="uq_5scr_campaign_risk_lock_v2_handoff"),
        sa.ForeignKeyConstraint(
            ["handoff_id", "tradeplan_id", "account_id", "account_snapshot_id"],
            [
                f"{HANDOFF}.handoff_id",
                f"{HANDOFF}.tradeplan_id",
                f"{HANDOFF}.account_id",
                f"{HANDOFF}.account_snapshot_id",
            ],
            name="fk_5scr_campaign_risk_lock_v2_handoff_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "risk_lock_id",
            "execution_campaign_id",
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "account_snapshot_id",
            name="uq_5scr_campaign_risk_lock_v2_reservation_scope",
        ),
        sa.UniqueConstraint(
            "risk_lock_id",
            "execution_campaign_id",
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "account_snapshot_id",
            "risk_unit_usd",
            name="uq_5scr_campaign_risk_lock_v2_reservation_risk_scope",
        ),
        sa.CheckConstraint(
            "risk_lock_id ~ '^5scr-c2-risk-lock-v2:[0-9a-f]{32}$' AND "
            "execution_campaign_id ~ '^5scr-execution-campaign-v2:[0-9a-f]{32}$' AND "
            "authority_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_campaign_risk_lock_v2_identity",
        ),
        sa.CheckConstraint(
            "policy_id='5scr.c2-shadow.parent-only.v2' AND balance_base > 0 AND "
            "risk_percent_per_entry = 0.05 AND risk_unit_usd > 0 AND "
            "risk_unit_usd = balance_base * risk_percent_per_entry AND "
            "max_campaign_risk_usd = risk_unit_usd * 2 AND "
            "max_campaign_risk_usd = balance_base * 0.10",
            name="ck_5scr_campaign_risk_lock_v2_amounts",
        ),
        sa.CheckConstraint(
            "risk_authority IS TRUE AND broker_execution_authority IS FALSE",
            name="ck_5scr_campaign_risk_lock_v2_authority",
        ),
        sa.CheckConstraint(
            "(state='ACTIVE' AND closed_at IS NULL AND terminal_reason IS NULL) OR "
            "(state='CLOSED' AND closed_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_5scr_campaign_risk_lock_v2_state",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_5scr_campaign_risk_lock_v2_state_version"),
    )
    op.create_index("ix_5scr_campaign_risk_lock_v2_account", RISK_LOCK, ["account_id", "locked_at"])
    op.create_index(
        "ix_5scr_c2_risk_lock_v2_snapshot",
        RISK_LOCK,
        ["account_snapshot_id"],
    )

    op.create_table(
        RESERVATION,
        sa.Column("reservation_id", sa.Text(), nullable=False),
        sa.Column("execution_campaign_id", sa.Text(), nullable=False),
        sa.Column("risk_lock_id", sa.Text(), nullable=False),
        sa.Column("handoff_id", sa.Text(), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("account_snapshot_hash", sa.String(length=71), nullable=False),
        sa.Column("governance_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("existing_risk_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("entry_role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("volume", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("stop_loss", sa.Numeric(28, 12), nullable=False),
        sa.Column("take_profit", sa.Numeric(28, 12), nullable=False),
        sa.Column("risk_unit_usd", sa.Numeric(28, 12), nullable=False),
        sa.Column("reserved_risk_usd", sa.Numeric(28, 12), nullable=False),
        sa.Column("symbol_capability_hash", sa.String(length=71), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("risk_authority", sa.Boolean(), nullable=False),
        sa.Column("valid_for_execution", sa.Boolean(), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("broker_execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=120), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("reservation_id", name="pk_5scr_risk_reservation_v2"),
        sa.UniqueConstraint(
            "execution_campaign_id",
            name="uq_5scr_risk_reservation_v2_campaign",
        ),
        sa.UniqueConstraint("risk_lock_id", name="uq_5scr_risk_reservation_v2_risk_lock"),
        sa.UniqueConstraint("handoff_id", name="uq_5scr_risk_reservation_v2_handoff"),
        sa.UniqueConstraint("tradeplan_id", name="uq_5scr_risk_reservation_v2_tradeplan"),
        sa.ForeignKeyConstraint(
            [
                "risk_lock_id",
                "execution_campaign_id",
                "handoff_id",
                "tradeplan_id",
                "account_id",
                "account_snapshot_id",
                "risk_unit_usd",
            ],
            [
                f"{RISK_LOCK}.risk_lock_id",
                f"{RISK_LOCK}.execution_campaign_id",
                f"{RISK_LOCK}.handoff_id",
                f"{RISK_LOCK}.tradeplan_id",
                f"{RISK_LOCK}.account_id",
                f"{RISK_LOCK}.account_snapshot_id",
                f"{RISK_LOCK}.risk_unit_usd",
            ],
            name="fk_5scr_risk_reservation_v2_lock_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "handoff_id",
                "tradeplan_id",
                "account_id",
                "executor_id",
                "broker_server",
                "account_snapshot_id",
                "account_snapshot_hash",
            ],
            [
                f"{HANDOFF}.handoff_id",
                f"{HANDOFF}.tradeplan_id",
                f"{HANDOFF}.account_id",
                f"{HANDOFF}.executor_id",
                f"{HANDOFF}.broker_server",
                f"{HANDOFF}.account_snapshot_id",
                f"{HANDOFF}.account_snapshot_hash",
            ],
            name="fk_5scr_risk_reservation_v2_handoff_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_snapshot_id", "executor_id", "account_id"],
            [
                "executor_account_snapshots.snapshot_id",
                "executor_account_snapshots.executor_id",
                "executor_account_snapshots.account_id",
            ],
            name="fk_5scr_risk_reservation_v2_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            "execution_campaign_id",
            "tradeplan_id",
            "executor_id",
            "account_id",
            "account_snapshot_id",
            "canonical_symbol",
            "direction",
            name="uq_5scr_risk_reservation_v2_campaign_scope",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            "execution_campaign_id",
            "tradeplan_id",
            "account_id",
            "canonical_symbol",
            "direction",
            name="uq_5scr_risk_reservation_v2_execution_campaign_scope",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            "execution_campaign_id",
            "tradeplan_id",
            "executor_id",
            "account_id",
            name="uq_5scr_risk_reservation_v2_evaluation_scope",
        ),
        sa.CheckConstraint(
            "reservation_id ~ '^5scr-c2-reservation-v2:[0-9a-f]{32}$' AND "
            "execution_campaign_id ~ '^5scr-execution-campaign-v2:[0-9a-f]{32}$' AND "
            "authority_hash ~ '^sha256:[0-9a-f]{64}$' AND account_snapshot_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND symbol_capability_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "governance_evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND "
            "existing_risk_evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_risk_reservation_v2_identity",
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED','RELEASED','INVALIDATED','EXPIRED','RECONCILIATION_REQUIRED') "
            "AND entry_role='PARENT' "
            "AND direction IN ('BUY','SELL') AND volume > 0 "
            "AND risk_unit_usd > 0 AND reserved_risk_usd > 0 AND reserved_risk_usd <= risk_unit_usd "
            "AND expires_at > reserved_at AND expires_at <= reserved_at + interval '300 seconds'",
            name="ck_5scr_risk_reservation_v2_state",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_5scr_risk_reservation_v2_state_version"),
        sa.CheckConstraint(
            "(state='RESERVED' AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(state IN ('RELEASED','INVALIDATED','EXPIRED','RECONCILIATION_REQUIRED') AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_5scr_risk_reservation_v2_lifecycle",
        ),
        sa.CheckConstraint(
            "((direction='BUY' AND stop_loss < entry_price AND entry_price < take_profit) OR "
            " (direction='SELL' AND take_profit < entry_price AND entry_price < stop_loss))",
            name="ck_5scr_risk_reservation_v2_geometry",
        ),
        sa.CheckConstraint(
            "risk_authority IS TRUE AND valid_for_execution IS TRUE AND execution_mode='SHADOW' AND "
            "broker_execution_authority IS FALSE AND command_authority IS FALSE",
            name="ck_5scr_risk_reservation_v2_authority",
        ),
    )
    op.create_index("ix_5scr_risk_reservation_v2_account_expiry", RESERVATION, ["account_id", "state", "expires_at"])
    op.create_index("ix_5scr_c2_reservation_v2_executor_state", RESERVATION, ["executor_id", "state"])
    op.create_index(
        "ix_5scr_c2_reservation_v2_snapshot_scope",
        RESERVATION,
        ["account_snapshot_id", "executor_id", "account_id"],
    )

    op.create_table(
        CAMPAIGN,
        sa.Column("execution_campaign_id", sa.Text(), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("reservation_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("risk_authority", sa.Boolean(), nullable=False),
        sa.Column("broker_execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=120), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("execution_campaign_id", name="pk_5scr_execution_campaign_v2"),
        sa.UniqueConstraint("tradeplan_id", name="uq_5scr_execution_campaign_v2_tradeplan"),
        sa.UniqueConstraint("reservation_id", name="uq_5scr_execution_campaign_v2_reservation"),
        sa.ForeignKeyConstraint(
            ["reservation_id", "execution_campaign_id", "tradeplan_id", "account_id", "canonical_symbol", "direction"],
            [
                f"{RESERVATION}.reservation_id",
                f"{RESERVATION}.execution_campaign_id",
                f"{RESERVATION}.tradeplan_id",
                f"{RESERVATION}.account_id",
                f"{RESERVATION}.canonical_symbol",
                f"{RESERVATION}.direction",
            ],
            name="fk_5scr_execution_campaign_v2_reservation_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "execution_campaign_id",
            "reservation_id",
            "tradeplan_id",
            "account_id",
            "canonical_symbol",
            "direction",
            name="uq_5scr_execution_campaign_v2_outbox_scope",
        ),
        sa.CheckConstraint(
            "execution_campaign_id ~ '^5scr-execution-campaign-v2:[0-9a-f]{32}$' AND authority_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_execution_campaign_v2_identity",
        ),
        sa.CheckConstraint(
            "state IN ('PARENT_PENDING','INVALIDATED','EXPIRED','RECONCILIATION_REQUIRED') AND direction IN ('BUY','SELL') AND execution_mode='SHADOW'",
            name="ck_5scr_execution_campaign_v2_state",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_5scr_execution_campaign_v2_state_version"),
        sa.CheckConstraint(
            "(state='PARENT_PENDING' AND terminal_at IS NULL AND terminal_reason IS NULL) OR (state IN ('INVALIDATED','EXPIRED','RECONCILIATION_REQUIRED') AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_5scr_execution_campaign_v2_lifecycle",
        ),
        sa.CheckConstraint(
            "risk_authority IS TRUE AND broker_execution_authority IS FALSE AND command_authority IS FALSE",
            name="ck_5scr_execution_campaign_v2_authority",
        ),
    )
    op.create_index("ix_5scr_execution_campaign_v2_account_state", CAMPAIGN, ["account_id", "state"])

    op.create_table(
        OUTBOX,
        sa.Column("outbox_id", sa.Text(), nullable=False),
        sa.Column("signal_id", sa.Text(), nullable=False),
        sa.Column("execution_campaign_id", sa.Text(), nullable=False),
        sa.Column("reservation_id", sa.Text(), nullable=False),
        sa.Column("tradeplan_id", sa.Text(), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column("handoff_id", sa.Text(), nullable=False),
        sa.Column("risk_lock_id", sa.Text(), nullable=False),
        sa.Column("account_snapshot_hash", sa.String(length=71), nullable=False),
        sa.Column("symbol_capability_hash", sa.String(length=71), nullable=False),
        sa.Column("governance_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("existing_risk_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("material_candidate_hash", sa.String(length=71), nullable=False),
        sa.Column("candidate_evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("entry_role", sa.String(length=16), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=71), nullable=False),
        sa.Column("authority_hash", sa.String(length=71), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("delivery_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("broker_execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("command_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=120), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("outbox_id", name="pk_5scr_final_signal_outbox_v2"),
        sa.UniqueConstraint("signal_id", name="uq_5scr_final_signal_outbox_v2_signal"),
        sa.UniqueConstraint(
            "execution_campaign_id",
            name="uq_5scr_final_signal_outbox_v2_campaign",
        ),
        sa.UniqueConstraint("reservation_id", name="uq_5scr_final_signal_outbox_v2_reservation"),
        sa.UniqueConstraint("tradeplan_id", name="uq_5scr_final_signal_outbox_v2_tradeplan"),
        sa.ForeignKeyConstraint(
            ["execution_campaign_id", "reservation_id", "tradeplan_id", "account_id", "canonical_symbol", "direction"],
            [
                f"{CAMPAIGN}.execution_campaign_id",
                f"{CAMPAIGN}.reservation_id",
                f"{CAMPAIGN}.tradeplan_id",
                f"{CAMPAIGN}.account_id",
                f"{CAMPAIGN}.canonical_symbol",
                f"{CAMPAIGN}.direction",
            ],
            name="fk_5scr_final_signal_outbox_v2_campaign_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "handoff_id",
                "tradeplan_id",
                "account_id",
                "executor_id",
                "broker_server",
                "account_snapshot_id",
                "account_snapshot_hash",
            ],
            [
                f"{HANDOFF}.handoff_id",
                f"{HANDOFF}.tradeplan_id",
                f"{HANDOFF}.account_id",
                f"{HANDOFF}.executor_id",
                f"{HANDOFF}.broker_server",
                f"{HANDOFF}.account_snapshot_id",
                f"{HANDOFF}.account_snapshot_hash",
            ],
            name="fk_5scr_final_signal_outbox_v2_handoff_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_snapshot_id", "executor_id", "account_id"],
            [
                "executor_account_snapshots.snapshot_id",
                "executor_account_snapshots.executor_id",
                "executor_account_snapshots.account_id",
            ],
            name="fk_5scr_final_signal_outbox_v2_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "risk_lock_id",
                "execution_campaign_id",
                "handoff_id",
                "tradeplan_id",
                "account_id",
                "account_snapshot_id",
            ],
            [
                f"{RISK_LOCK}.risk_lock_id",
                f"{RISK_LOCK}.execution_campaign_id",
                f"{RISK_LOCK}.handoff_id",
                f"{RISK_LOCK}.tradeplan_id",
                f"{RISK_LOCK}.account_id",
                f"{RISK_LOCK}.account_snapshot_id",
            ],
            name="fk_5scr_final_signal_outbox_v2_risk_lock_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "reservation_id",
                "execution_campaign_id",
                "tradeplan_id",
                "executor_id",
                "account_id",
                "account_snapshot_id",
                "canonical_symbol",
                "direction",
            ],
            [
                f"{RESERVATION}.reservation_id",
                f"{RESERVATION}.execution_campaign_id",
                f"{RESERVATION}.tradeplan_id",
                f"{RESERVATION}.executor_id",
                f"{RESERVATION}.account_id",
                f"{RESERVATION}.account_snapshot_id",
                f"{RESERVATION}.canonical_symbol",
                f"{RESERVATION}.direction",
            ],
            name="fk_5scr_final_signal_outbox_v2_reservation_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "outbox_id ~ '^5scr-c2-outbox-v2:[0-9a-f]{32}$' AND signal_id ~ '^5scr-signal-shadow-v2:[0-9a-f]{32}$' AND payload_hash ~ '^sha256:[0-9a-f]{64}$' AND authority_hash ~ '^sha256:[0-9a-f]{64}$' AND account_snapshot_hash ~ '^sha256:[0-9a-f]{64}$' AND symbol_capability_hash ~ '^sha256:[0-9a-f]{64}$' AND governance_evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND existing_risk_evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND material_candidate_hash ~ '^sha256:[0-9a-f]{64}$' AND candidate_evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_final_signal_outbox_v2_identity",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','CANCELLED') AND entry_role='PARENT' AND direction IN ('BUY','SELL') AND delivery_authority IS FALSE AND broker_execution_authority IS FALSE AND command_authority IS FALSE",
            name="ck_5scr_final_signal_outbox_v2_dark",
        ),
        sa.CheckConstraint(
            "(status='PENDING' AND terminal_at IS NULL AND terminal_reason IS NULL) OR (status='CANCELLED' AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_5scr_final_signal_outbox_v2_lifecycle",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_5scr_final_signal_outbox_v2_state_version"),
        sa.CheckConstraint(
            "jsonb_typeof(payload)='object' AND (payload ->> 'event'='signal_json') IS TRUE "
            "AND (payload ->> 'signal_valid')::boolean IS TRUE "
            "AND (payload ->> 'is_final_signal')::boolean IS TRUE "
            "AND (payload ->> 'execution_valid_now')::boolean IS TRUE "
            "AND (payload ->> 'valid_for_execution')::boolean IS TRUE "
            "AND (payload ->> 'risk_authority')::boolean IS TRUE "
            "AND (payload ->> 'execution_mode'='SHADOW') IS TRUE "
            "AND (payload ->> 'next_required_stage'='C3_MANUAL_SHADOW_PROMOTION') IS TRUE "
            "AND (payload ->> 'broker_execution_authority')::boolean IS FALSE "
            "AND (payload ->> 'command_authority')::boolean IS FALSE "
            "AND (payload ->> 'delivery_authority')::boolean IS FALSE",
            name="ck_5scr_final_signal_outbox_v2_payload",
        ),
    )
    op.create_index("ix_5scr_final_signal_outbox_v2_status", OUTBOX, ["status", "created_at"])
    op.create_index(
        "ix_5scr_c2_outbox_v2_handoff_scope",
        OUTBOX,
        [
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "executor_id",
            "broker_server",
            "account_snapshot_id",
            "account_snapshot_hash",
        ],
    )
    op.create_index(
        "ix_5scr_c2_outbox_v2_risk_lock_scope",
        OUTBOX,
        [
            "risk_lock_id",
            "execution_campaign_id",
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "account_snapshot_id",
        ],
    )
    op.create_index(
        "ix_5scr_c2_outbox_v2_snapshot_scope",
        OUTBOX,
        ["account_snapshot_id", "executor_id", "account_id"],
    )

    op.create_table(
        EVALUATION,
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        *_candidate_columns(),
        sa.Column("evaluation_sequence", sa.Integer(), nullable=False),
        sa.Column("source_request_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_snapshot_id",
            sa.String(length=200),
            sa.Computed("build_evidence_payload #>> '{account_snapshot,snapshot_id}'", persisted=True),
            nullable=False,
        ),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("evidence_hash", sa.String(length=71), nullable=False),
        sa.Column("material_evaluation_hash", sa.String(length=71), nullable=False),
        sa.Column("result_execution_campaign_id", sa.Text(), nullable=True),
        sa.Column("result_reservation_id", sa.Text(), nullable=True),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("build_evidence_payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("evaluation_id", name="pk_5scr_candidate_c2_evaluation_v2"),
        _candidate_fk("fk_5scr_candidate_c2_evaluation_v2_candidate_scope"),
        sa.ForeignKeyConstraint(
            ["account_snapshot_id", "executor_id", "account_id"],
            [
                "executor_account_snapshots.snapshot_id",
                "executor_account_snapshots.executor_id",
                "executor_account_snapshots.account_id",
            ],
            name="fk_5scr_candidate_c2_evaluation_v2_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_reservation_id", "result_execution_campaign_id", "tradeplan_id", "executor_id", "account_id"],
            [
                f"{RESERVATION}.reservation_id",
                f"{RESERVATION}.execution_campaign_id",
                f"{RESERVATION}.tradeplan_id",
                f"{RESERVATION}.executor_id",
                f"{RESERVATION}.account_id",
            ],
            name="fk_5scr_candidate_c2_evaluation_v2_result_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tradeplan_id", "evaluation_sequence", name="uq_5scr_candidate_c2_evaluation_v2_sequence"),
        sa.UniqueConstraint("tradeplan_id", "source_request_id", name="uq_5scr_candidate_c2_evaluation_v2_request"),
        sa.UniqueConstraint("tradeplan_id", "decision_at", name="uq_5scr_candidate_c2_evaluation_v2_clock"),
        sa.CheckConstraint(
            "evaluation_id ~ '^5scr-c2-eval-v2:[0-9a-f]{32}$' AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND material_evaluation_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_candidate_c2_evaluation_v2_identity",
        ),
        sa.CheckConstraint(
            "evaluation_sequence >= 1 AND decision IN ('APPROVED','WAIT','REJECTED') AND reason_code ~ '^[A-Z0-9_]{3,120}$'",
            name="ck_5scr_candidate_c2_evaluation_v2_decision",
        ),
        sa.CheckConstraint(
            "(decision='APPROVED' AND result_execution_campaign_id IS NOT NULL AND result_reservation_id IS NOT NULL) OR (decision IN ('WAIT','REJECTED') AND result_execution_campaign_id IS NULL AND result_reservation_id IS NULL)",
            name="ck_5scr_candidate_c2_evaluation_v2_result",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE AND jsonb_typeof(payload)='object' AND jsonb_typeof(build_evidence_payload)='object'",
            name="ck_5scr_candidate_c2_evaluation_v2_shadow",
        ),
    )
    op.create_index(
        "ix_5scr_candidate_c2_evaluation_v2_history",
        EVALUATION,
        ["tradeplan_id", "evaluation_sequence", "evaluation_id"],
    )
    op.create_index(
        "ix_5scr_c2_evaluation_v2_candidate_scope",
        EVALUATION,
        _CANDIDATE_SCOPE,
    )
    op.create_index(
        "ix_5scr_c2_evaluation_v2_result_scope",
        EVALUATION,
        ["result_reservation_id", "result_execution_campaign_id", "tradeplan_id", "executor_id", "account_id"],
    )
    op.create_index(
        "ix_5scr_c2_evaluation_v2_snapshot_scope",
        EVALUATION,
        ["account_snapshot_id", "executor_id", "account_id"],
    )

    op.create_foreign_key(
        "fk_5scr_campaign_risk_lock_v2_campaign",
        RISK_LOCK,
        CAMPAIGN,
        ["execution_campaign_id"],
        ["execution_campaign_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_5scr_risk_reservation_v2_campaign",
        RESERVATION,
        CAMPAIGN,
        ["execution_campaign_id"],
        ["execution_campaign_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    # Formation/evaluation rows are append-only. Operational rows have narrow
    # terminal transitions installed separately below.
    immutable_names = {
        HANDOFF: ("strategy_5scr_reject_c2_handoff_v2_mutation", "trg_5scr_reject_c2_handoff_v2_mutation"),
        EVALUATION: (
            "strategy_5scr_reject_c2_evaluation_v2_mutation",
            "trg_5scr_reject_c2_evaluation_v2_mutation",
        ),
    }
    for table, (function, trigger) in immutable_names.items():
        op.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'immutable P7 C2 SHADOW authority row'
                    USING ERRCODE='23514', CONSTRAINT='ck_5scr_candidate_c2_shadow_v2_immutable';
            END $$;
            CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )

    transition_specs = {
        RISK_LOCK: ("state", "ACTIVE", "CLOSED", "closed_at", True),
        RESERVATION: ("state", "RESERVED", "RELEASED,INVALIDATED,EXPIRED,RECONCILIATION_REQUIRED", "terminal_at", True),
        CAMPAIGN: ("state", "PARENT_PENDING", "INVALIDATED,EXPIRED,RECONCILIATION_REQUIRED", "terminal_at", True),
        OUTBOX: ("status", "PENDING", "CANCELLED", "terminal_at", True),
    }
    for table, (state_column, initial, terminal_csv, clock_column, versioned) in transition_specs.items():
        function = f"strategy_5scr_guard_{table}_transition"
        trigger = f"trg_5scr_guard_{table}_transition"
        terminals = ",".join(f"'{item}'" for item in terminal_csv.split(","))
        clock_decl = "timestamp with time zone"
        op.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE desired_state text; desired_clock {clock_decl}; desired_reason text;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'immutable P7 C2 SHADOW authority row'
                        USING ERRCODE='23514', CONSTRAINT='ck_5scr_candidate_c2_shadow_v2_immutable';
                END IF;
                desired_state := NEW.{state_column};
                desired_clock := NEW.{clock_column};
                desired_reason := NEW.terminal_reason;
                IF OLD.{state_column} <> '{initial}' OR NEW.{state_column} NOT IN ({terminals}) OR
                   NEW.{clock_column} IS NULL OR NEW.terminal_reason IS NULL THEN
                    RAISE EXCEPTION 'invalid P7 C2 SHADOW terminal transition'
                        USING ERRCODE='23514', CONSTRAINT='ck_5scr_candidate_c2_shadow_v2_transition';
                END IF;
                {"IF NEW.state_version <> OLD.state_version + 1 THEN RAISE EXCEPTION 'P7 state version must advance exactly once' USING ERRCODE='23514', CONSTRAINT='ck_5scr_candidate_c2_shadow_v2_transition'; END IF;" if versioned else ""}
                -- Only lifecycle metadata may change.
                NEW.{state_column} := OLD.{state_column}; NEW.{clock_column} := OLD.{clock_column};
                NEW.terminal_reason := OLD.terminal_reason;
                {"NEW.state_version := OLD.state_version;" if versioned else ""}
                IF to_jsonb(NEW) <> to_jsonb(OLD) THEN
                    RAISE EXCEPTION 'immutable P7 C2 SHADOW authority drift'
                        USING ERRCODE='23514', CONSTRAINT='ck_5scr_candidate_c2_shadow_v2_immutable';
                END IF;
                NEW.{state_column} := desired_state;
                NEW.{clock_column} := desired_clock;
                NEW.terminal_reason := desired_reason;
                {"NEW.state_version := OLD.state_version + 1;" if versioned else ""}
                RETURN NEW;
            END $$;
            CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )

    # Close the account-wide race in both directions.  P7 takes a SHARE table
    # fence on execution_commands before deriving risk, so an INSERT/UPDATE
    # either commits first and is observed by P7, or waits for P7 and is
    # rejected here.  UPDATE coverage also prevents direct resurrection of a
    # terminal-safe command while live P7 authority exists.
    # Do not take the account advisory lock in this trigger: an INSERT already
    # owns ROW EXCLUSIVE on execution_commands and doing so would invert P7's
    # advisory -> SHARE order.
    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_execution_command_against_c2_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            conflicts_with_c2 boolean;
            new_executor_account text;
            old_executor_account text;
        BEGIN
            SELECT account_id INTO new_executor_account
            FROM executor_instances WHERE executor_id=NEW.executor_id;
            IF new_executor_account IS NULL OR new_executor_account IS DISTINCT FROM NEW.account_id THEN
                RAISE EXCEPTION 'execution command executor/account binding is invalid'
                    USING ERRCODE='23514', CONSTRAINT='ck_execution_command_executor_account_binding_c2_v2';
            END IF;
            IF TG_OP='UPDATE' THEN
                SELECT account_id INTO old_executor_account
                FROM executor_instances WHERE executor_id=OLD.executor_id;
                -- Binding fields are command identity, not lifecycle metadata.
                -- Terminal cleanup may advance state/report fields only.
                IF NEW.account_id IS DISTINCT FROM OLD.account_id
                   OR NEW.executor_id IS DISTINCT FROM OLD.executor_id
                   OR old_executor_account IS NULL
                   OR old_executor_account IS DISTINCT FROM OLD.account_id THEN
                    RAISE EXCEPTION 'execution command executor/account binding is immutable'
                        USING ERRCODE='23514', CONSTRAINT='ck_execution_command_executor_account_binding_c2_v2';
                END IF;
            END IF;
            IF NEW.state NOT IN ('REJECTED','SHADOW_COMPLETED','SHADOW_REJECTED') THEN
                conflicts_with_c2 :=
                    EXISTS (
                        SELECT 1 FROM {RISK_LOCK}
                        WHERE account_id=NEW.account_id AND state='ACTIVE'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RESERVATION}
                        WHERE account_id=NEW.account_id AND state='RESERVED'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RISK_LOCK}
                        WHERE account_id=new_executor_account AND state='ACTIVE'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RESERVATION}
                        WHERE account_id=new_executor_account AND state='RESERVED'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RISK_LOCK} risk_lock
                        JOIN {HANDOFF} handoff ON handoff.handoff_id=risk_lock.handoff_id
                        WHERE handoff.executor_id=NEW.executor_id AND risk_lock.state='ACTIVE'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RESERVATION}
                        WHERE executor_id=NEW.executor_id AND state='RESERVED'
                    );
                -- UPDATE checks both old bindings even though identity mutation
                -- is forbidden above, making the authority fence explicit and
                -- fail-closed if historical command data is inconsistent.
                IF TG_OP='UPDATE' AND NOT conflicts_with_c2 THEN
                    conflicts_with_c2 :=
                        EXISTS (
                            SELECT 1 FROM {RISK_LOCK}
                            WHERE account_id=OLD.account_id AND state='ACTIVE'
                        )
                        OR EXISTS (
                        SELECT 1 FROM {RESERVATION}
                        WHERE account_id=OLD.account_id AND state='RESERVED'
                        )
                        OR EXISTS (
                            SELECT 1 FROM {RISK_LOCK}
                            WHERE account_id=old_executor_account AND state='ACTIVE'
                        )
                        OR EXISTS (
                            SELECT 1 FROM {RESERVATION}
                            WHERE account_id=old_executor_account AND state='RESERVED'
                        )
                        OR EXISTS (
                            SELECT 1 FROM {RISK_LOCK} risk_lock
                            JOIN {HANDOFF} handoff ON handoff.handoff_id=risk_lock.handoff_id
                            WHERE handoff.executor_id=OLD.executor_id AND risk_lock.state='ACTIVE'
                        )
                        OR EXISTS (
                            SELECT 1 FROM {RESERVATION}
                            WHERE executor_id=OLD.executor_id AND state='RESERVED'
                        );
                END IF;
                IF conflicts_with_c2 THEN
                    RAISE EXCEPTION 'execution command conflicts with live P7 C2 SHADOW risk authority'
                        USING ERRCODE='23514', CONSTRAINT='ck_execution_command_no_live_c2_shadow_v2';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_execution_command_against_c2_v2
        BEFORE INSERT OR UPDATE ON execution_commands
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_execution_command_against_c2_v2();
        """
    )

    # Executor account/server identity is durable authority scope.  Mode,
    # revocation and heartbeat updates remain available, but a direct identity
    # rebind cannot launder commands around live P7 authority.  The P7 writer
    # takes NO KEY UPDATE on this row, so this trigger serializes on the row
    # without adding an account advisory or a table-lock inversion.
    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_executor_identity_against_c2_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            conflicts_with_c2 boolean;
        BEGIN
            IF NEW.executor_id IS DISTINCT FROM OLD.executor_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.broker_server IS DISTINCT FROM OLD.broker_server THEN
                conflicts_with_c2 :=
                    EXISTS (
                        SELECT 1 FROM {RISK_LOCK} risk_lock
                        JOIN {HANDOFF} handoff ON handoff.handoff_id=risk_lock.handoff_id
                        WHERE risk_lock.state='ACTIVE'
                          AND (
                              handoff.executor_id IN (OLD.executor_id,NEW.executor_id)
                              OR risk_lock.account_id IN (OLD.account_id,NEW.account_id)
                          )
                    )
                    OR EXISTS (
                        SELECT 1 FROM {RESERVATION}
                        WHERE state='RESERVED'
                          AND (
                              executor_id IN (OLD.executor_id,NEW.executor_id)
                              OR account_id IN (OLD.account_id,NEW.account_id)
                          )
                    );
                IF conflicts_with_c2 THEN
                    RAISE EXCEPTION 'executor identity mutation conflicts with live P7 C2 SHADOW authority'
                        USING ERRCODE='23514', CONSTRAINT='ck_executor_identity_no_live_c2_shadow_v2';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_executor_identity_against_c2_v2
        BEFORE UPDATE ON executor_instances
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_executor_identity_against_c2_v2();
        """
    )

    # Legacy risk writers already serialize account authority with this same
    # advisory key.  Re-acquiring it inside the trigger is transaction-local
    # and re-entrant for compliant writers, while also protecting direct SQL.
    # Terminal cleanup states deliberately bypass the guard: CLOSED and
    # RELEASED/EXPIRED reduce authority and must remain possible after P7 forms.
    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_legacy_campaign_risk_against_c2_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.state='ACTIVE' THEN
                PERFORM pg_advisory_xact_lock(hashtextextended(NEW.account_id,0));
                IF EXISTS (
                    SELECT 1 FROM {RISK_LOCK}
                    WHERE account_id=NEW.account_id AND state='ACTIVE'
                ) OR EXISTS (
                    SELECT 1 FROM {RESERVATION}
                    WHERE account_id=NEW.account_id AND state='RESERVED'
                ) THEN
                    RAISE EXCEPTION 'legacy campaign risk conflicts with live P7 C2 SHADOW authority'
                        USING ERRCODE='23514', CONSTRAINT='ck_5scr_legacy_campaign_no_live_c2_shadow_v2';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_legacy_campaign_risk_against_c2_v2
        BEFORE INSERT OR UPDATE ON strategy_5scr_campaign_risk_locks
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_legacy_campaign_risk_against_c2_v2();
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_legacy_reservation_against_c2_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.state IN ('HELD','CONSUMED','OPEN') THEN
                PERFORM pg_advisory_xact_lock(hashtextextended(NEW.account_id,0));
                IF EXISTS (
                    SELECT 1 FROM {RISK_LOCK}
                    WHERE account_id=NEW.account_id AND state='ACTIVE'
                ) OR EXISTS (
                    SELECT 1 FROM {RESERVATION}
                    WHERE account_id=NEW.account_id AND state='RESERVED'
                ) THEN
                    RAISE EXCEPTION 'legacy reservation conflicts with live P7 C2 SHADOW authority'
                        USING ERRCODE='23514', CONSTRAINT='ck_5scr_legacy_reservation_no_live_c2_shadow_v2';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_legacy_reservation_against_c2_v2
        BEFORE INSERT OR UPDATE ON strategy_5scr_risk_reservations
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_legacy_reservation_against_c2_v2();
        """
    )


def downgrade() -> None:
    cross_authority_guards = {
        "execution_commands": (
            "trg_5scr_guard_execution_command_against_c2_v2",
            "strategy_5scr_guard_execution_command_against_c2_v2",
        ),
        "executor_instances": (
            "trg_5scr_guard_executor_identity_against_c2_v2",
            "strategy_5scr_guard_executor_identity_against_c2_v2",
        ),
        "strategy_5scr_campaign_risk_locks": (
            "trg_5scr_guard_legacy_campaign_risk_against_c2_v2",
            "strategy_5scr_guard_legacy_campaign_risk_against_c2_v2",
        ),
        "strategy_5scr_risk_reservations": (
            "trg_5scr_guard_legacy_reservation_against_c2_v2",
            "strategy_5scr_guard_legacy_reservation_against_c2_v2",
        ),
    }
    for table, (trigger, function) in cross_authority_guards.items():
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    for table in (OUTBOX, CAMPAIGN, RESERVATION, RISK_LOCK):
        trigger = f"trg_5scr_guard_{table}_transition"
        function = f"strategy_5scr_guard_{table}_transition"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    immutable_names = {
        HANDOFF: ("strategy_5scr_reject_c2_handoff_v2_mutation", "trg_5scr_reject_c2_handoff_v2_mutation"),
        EVALUATION: (
            "strategy_5scr_reject_c2_evaluation_v2_mutation",
            "trg_5scr_reject_c2_evaluation_v2_mutation",
        ),
    }
    for table, (function, trigger) in immutable_names.items():
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    # Break the two deferred formation cycles before dropping the campaign.
    op.drop_constraint("fk_5scr_campaign_risk_lock_v2_campaign", RISK_LOCK, type_="foreignkey")
    op.drop_constraint("fk_5scr_risk_reservation_v2_campaign", RESERVATION, type_="foreignkey")
    op.drop_index("ix_5scr_c2_evaluation_v2_snapshot_scope", table_name=EVALUATION)
    op.drop_index("ix_5scr_c2_evaluation_v2_result_scope", table_name=EVALUATION)
    op.drop_index("ix_5scr_c2_evaluation_v2_candidate_scope", table_name=EVALUATION)
    op.drop_index("ix_5scr_candidate_c2_evaluation_v2_history", table_name=EVALUATION)
    op.drop_table(EVALUATION)
    op.drop_index("ix_5scr_c2_outbox_v2_snapshot_scope", table_name=OUTBOX)
    op.drop_index("ix_5scr_c2_outbox_v2_risk_lock_scope", table_name=OUTBOX)
    op.drop_index("ix_5scr_c2_outbox_v2_handoff_scope", table_name=OUTBOX)
    op.drop_index("ix_5scr_final_signal_outbox_v2_status", table_name=OUTBOX)
    op.drop_table(OUTBOX)
    op.drop_index("ix_5scr_execution_campaign_v2_account_state", table_name=CAMPAIGN)
    op.drop_table(CAMPAIGN)
    op.drop_index("ix_5scr_risk_reservation_v2_account_expiry", table_name=RESERVATION)
    op.drop_index("ix_5scr_c2_reservation_v2_executor_state", table_name=RESERVATION)
    op.drop_index("ix_5scr_c2_reservation_v2_snapshot_scope", table_name=RESERVATION)
    op.drop_table(RESERVATION)
    op.drop_index("ix_5scr_c2_risk_lock_v2_snapshot", table_name=RISK_LOCK)
    op.drop_index("ix_5scr_campaign_risk_lock_v2_account", table_name=RISK_LOCK)
    op.drop_table(RISK_LOCK)
    op.drop_index("ix_5scr_c2_handoff_v2_snapshot_scope", table_name=HANDOFF)
    op.drop_index("ix_5scr_c2_handoff_v2_executor", table_name=HANDOFF)
    op.drop_index("ix_5scr_candidate_c2_handoff_v2_lifecycle", table_name=HANDOFF)
    op.drop_table(HANDOFF)
    op.drop_constraint(
        "uq_5scr_tradeplan_candidate_v2_c2_scope", "strategy_5scr_tradeplan_candidates_v2", type_="unique"
    )
    op.execute("DROP TRIGGER trg_5scr_guard_account_snapshot_c2_update_v2 ON executor_account_snapshots")
    op.execute("DROP FUNCTION strategy_5scr_guard_account_snapshot_c2_update_v2()")
    op.drop_constraint(
        "ck_executor_account_snapshot_c2_reconciliation_v2",
        "executor_account_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "uq_executor_account_snapshot_c2_scope_v2",
        "executor_account_snapshots",
        type_="unique",
    )
    op.drop_column("executor_account_snapshots", "pending_order_count")
    op.drop_column("executor_account_snapshots", "broker_ledger_reconciled")
