"""Add durable 5S-CR campaign locks, reservations, and final-signal outbox.

Revision ID: 20260803_03
Revises: 20260803_02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260803_03"
down_revision = "20260803_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_5scr_campaign_risk_locks",
        sa.Column("campaign_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column(
            "executor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("executor_instances.executor_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "account_snapshot_id",
            sa.String(length=200),
            sa.ForeignKey("executor_account_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("balance_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("risk_percent_per_entry", sa.Numeric(12, 10), nullable=False),
        sa.Column("risk_unit_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_campaign_risk_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('ACTIVE', 'CLOSED')", name="ck_5scr_campaign_risk_lock_state_v1"),
        sa.CheckConstraint(
            "balance_base > 0 AND risk_percent_per_entry > 0 "
            "AND risk_unit_usd > 0 AND max_campaign_risk_usd >= risk_unit_usd",
            name="ck_5scr_campaign_risk_lock_amounts_v1",
        ),
        sa.CheckConstraint(
            "(state = 'ACTIVE' AND closed_at IS NULL) OR (state = 'CLOSED' AND closed_at IS NOT NULL)",
            name="ck_5scr_campaign_risk_lock_lifecycle_v1",
        ),
        sa.PrimaryKeyConstraint("campaign_id", "account_id", name="pk_5scr_campaign_risk_locks_v1"),
    )
    op.create_index(
        "ix_5scr_campaign_risk_locks_account_state",
        "strategy_5scr_campaign_risk_locks",
        ["account_id", "state"],
    )

    op.create_table(
        "strategy_5scr_risk_reservations",
        sa.Column("reservation_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("campaign_id", sa.Text(), nullable=False),
        sa.Column(
            "tradeplan_id",
            sa.String(length=80),
            sa.ForeignKey("strategy_5scr_tradeplan_candidates.tradeplan_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "executor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("executor_instances.executor_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column(
            "account_snapshot_id",
            sa.String(length=200),
            sa.ForeignKey("executor_account_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("signal_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("signal_hash", sa.String(length=80), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'HELD'")),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("entry_role", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("volume", sa.Numeric(24, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 12), nullable=False),
        sa.Column("stop_loss", sa.Numeric(24, 12), nullable=False),
        sa.Column("take_profit", sa.Numeric(24, 12), nullable=False),
        sa.Column("risk_unit_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("reserved_risk_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("balance_snapshot", sa.Numeric(24, 8), nullable=False),
        sa.Column("equity_snapshot", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "command_id",
            UUID(as_uuid=True),
            sa.ForeignKey("execution_commands.command_id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('HELD', 'CONSUMED', 'OPEN', 'RELEASED', 'EXPIRED')",
            name="ck_5scr_risk_reservation_state_v1",
        ),
        sa.CheckConstraint(
            "entry_role = 'PARENT' AND direction IN ('BUY', 'SELL')",
            name="ck_5scr_risk_reservation_parent_only_v1",
        ),
        sa.CheckConstraint(
            "volume > 0 AND entry_price > 0 AND stop_loss > 0 AND take_profit > 0 "
            "AND risk_unit_usd > 0 AND reserved_risk_usd > 0 "
            "AND reserved_risk_usd <= risk_unit_usd "
            "AND balance_snapshot > 0 AND equity_snapshot > 0",
            name="ck_5scr_risk_reservation_amounts_v1",
        ),
        sa.CheckConstraint(
            "expires_at > reserved_at AND expires_at <= reserved_at + interval '300 seconds'",
            name="ck_5scr_risk_reservation_expiry_v1",
        ),
        sa.CheckConstraint(
            "(direction = 'BUY' AND stop_loss < entry_price AND entry_price < take_profit) "
            "OR (direction = 'SELL' AND take_profit < entry_price AND entry_price < stop_loss)",
            name="ck_5scr_risk_reservation_geometry_v1",
        ),
        sa.CheckConstraint(
            "source_candidate_hash ~ '^[0-9a-f]{64}$' "
            "AND signal_id ~ '^5scr-signal:[0-9a-f]{32}$' "
            "AND signal_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_5scr_risk_reservation_hashes_v1",
        ),
        sa.CheckConstraint(
            "(state = 'HELD' AND command_id IS NULL AND consumed_at IS NULL "
            " AND opened_at IS NULL AND released_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'CONSUMED' AND command_id IS NOT NULL AND consumed_at IS NOT NULL "
            " AND opened_at IS NULL AND released_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'OPEN' AND command_id IS NOT NULL AND consumed_at IS NOT NULL "
            " AND opened_at IS NOT NULL AND released_at IS NULL AND expired_at IS NULL) OR "
            "(state = 'RELEASED' AND released_at IS NOT NULL AND expired_at IS NULL) OR "
            "(state = 'EXPIRED' AND command_id IS NULL AND consumed_at IS NULL "
            " AND opened_at IS NULL AND released_at IS NULL AND expired_at IS NOT NULL)",
            name="ck_5scr_risk_reservation_lifecycle_v1",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id", "account_id"],
            [
                "strategy_5scr_campaign_risk_locks.campaign_id",
                "strategy_5scr_campaign_risk_locks.account_id",
            ],
            name="fk_5scr_risk_reservation_campaign_lock_v1",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            "campaign_id",
            "tradeplan_id",
            "signal_id",
            "executor_id",
            "account_id",
            "account_snapshot_id",
            "canonical_symbol",
            "broker_symbol",
            "direction",
            name="uq_5scr_risk_reservation_outbox_binding_v1",
        ),
    )
    op.create_index(
        "ix_5scr_risk_reservations_account_state",
        "strategy_5scr_risk_reservations",
        ["account_id", "state", "expires_at"],
    )
    op.create_index(
        "ix_5scr_risk_reservations_campaign_state",
        "strategy_5scr_risk_reservations",
        ["campaign_id", "state"],
    )
    op.create_index(
        "uq_5scr_risk_reservation_active_parent",
        "strategy_5scr_risk_reservations",
        ["campaign_id", "account_id", "entry_role"],
        unique=True,
        postgresql_where=sa.text("state IN ('HELD', 'CONSUMED', 'OPEN')"),
    )

    op.create_table(
        "strategy_5scr_final_signal_outbox",
        sa.Column("outbox_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("campaign_id", sa.Text(), nullable=False),
        sa.Column(
            "tradeplan_id",
            sa.String(length=80),
            sa.ForeignKey("strategy_5scr_tradeplan_candidates.tradeplan_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("signal_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CLAIMED', 'PUBLISHED', 'DEAD')",
            name="ck_5scr_final_signal_outbox_status_v1",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_5scr_final_signal_outbox_attempts_v1"),
        sa.CheckConstraint(
            "(status = 'PENDING' AND lease_owner IS NULL AND lease_expires_at IS NULL AND published_at IS NULL) OR "
            "(status = 'CLAIMED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            " AND published_at IS NULL) OR "
            "(status = 'PUBLISHED' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            " AND published_at IS NOT NULL) OR "
            "(status = 'DEAD' AND lease_owner IS NULL AND lease_expires_at IS NULL AND published_at IS NULL)",
            name="ck_5scr_final_signal_outbox_lifecycle_v1",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^sha256:[0-9a-f]{64}$' AND signal_id ~ '^5scr-signal:[0-9a-f]{32}$'",
            name="ck_5scr_final_signal_outbox_hashes_v1",
        ),
        sa.CheckConstraint(
            "payload ?& ARRAY['event','schema_version','signal_id','tradeplan_id','lifecycle_id',"
            "'symbol','broker_symbol','final_direction','signal_valid','is_final_signal',"
            "'execution_valid_now','valid_for_execution','risk_reservation_id','risk_snapshot_id',"
            "'reserved_volume','risk_reservation'] "
            "AND jsonb_typeof(payload -> 'risk_reservation') = 'object' "
            "AND (payload -> 'risk_reservation') ?& "
            "    ARRAY['reservation_id','campaign_id','tradeplan_id','canonical_symbol',"
            "          'broker_symbol','direction','state','entry_role','policy_id',"
            "          'risk_snapshot_id','reserved_volume'] "
            "AND payload ->> 'event' = 'signal_json' "
            "AND payload ->> 'schema_version' = 'wolf15.strategy-5scr.final-signal.v1' "
            "AND (payload ->> 'is_final_signal')::boolean IS TRUE "
            "AND (payload ->> 'valid_for_execution')::boolean IS TRUE "
            "AND (payload ->> 'execution_valid_now')::boolean IS TRUE "
            "AND (payload ->> 'signal_valid')::boolean IS TRUE "
            "AND payload ->> 'signal_id' = signal_id "
            "AND payload ->> 'tradeplan_id' = tradeplan_id "
            "AND payload ->> 'lifecycle_id' = campaign_id "
            "AND payload ->> 'symbol' = canonical_symbol "
            "AND payload ->> 'broker_symbol' = broker_symbol "
            "AND payload ->> 'final_direction' = direction "
            "AND payload ->> 'risk_reservation_id' = reservation_id::text "
            "AND payload ->> 'risk_snapshot_id' = account_snapshot_id "
            "AND (payload ->> 'reserved_volume')::numeric = "
            "    (payload #>> '{risk_reservation,reserved_volume}')::numeric "
            "AND payload #>> '{risk_reservation,reservation_id}' = reservation_id::text "
            "AND payload #>> '{risk_reservation,campaign_id}' = campaign_id "
            "AND payload #>> '{risk_reservation,tradeplan_id}' = tradeplan_id "
            "AND payload #>> '{risk_reservation,canonical_symbol}' = canonical_symbol "
            "AND payload #>> '{risk_reservation,broker_symbol}' = broker_symbol "
            "AND payload #>> '{risk_reservation,direction}' = direction "
            "AND payload #>> '{risk_reservation,risk_snapshot_id}' = account_snapshot_id "
            "AND payload #>> '{risk_reservation,state}' = 'HELD' "
            "AND payload #>> '{risk_reservation,entry_role}' = 'PARENT' "
            "AND payload #>> '{risk_reservation,policy_id}' = '5scr.production-adjusted.parent-only.v1' "
            "AND NOT (payload ?| ARRAY['account_id','account_number','executor_id','login_hash','token',"
            "'verification_key','balance','equity']) "
            "AND NOT ((payload -> 'risk_reservation') ?| ARRAY['account_id','account_number','executor_id',"
            "'login_hash','token','verification_key','balance','equity'])",
            name="ck_5scr_final_signal_outbox_payload_v1",
        ),
        sa.ForeignKeyConstraint(
            [
                "reservation_id",
                "campaign_id",
                "tradeplan_id",
                "signal_id",
                "executor_id",
                "account_id",
                "account_snapshot_id",
                "canonical_symbol",
                "broker_symbol",
                "direction",
            ],
            [
                "strategy_5scr_risk_reservations.reservation_id",
                "strategy_5scr_risk_reservations.campaign_id",
                "strategy_5scr_risk_reservations.tradeplan_id",
                "strategy_5scr_risk_reservations.signal_id",
                "strategy_5scr_risk_reservations.executor_id",
                "strategy_5scr_risk_reservations.account_id",
                "strategy_5scr_risk_reservations.account_snapshot_id",
                "strategy_5scr_risk_reservations.canonical_symbol",
                "strategy_5scr_risk_reservations.broker_symbol",
                "strategy_5scr_risk_reservations.direction",
            ],
            name="fk_5scr_final_signal_outbox_reservation_binding_v1",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_5scr_final_signal_outbox_delivery",
        "strategy_5scr_final_signal_outbox",
        ["status", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION enforce_5scr_campaign_risk_lock_update_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.executor_id IS DISTINCT FROM OLD.executor_id
               OR NEW.account_snapshot_id IS DISTINCT FROM OLD.account_snapshot_id
               OR NEW.policy_id IS DISTINCT FROM OLD.policy_id
               OR NEW.balance_base IS DISTINCT FROM OLD.balance_base
               OR NEW.risk_percent_per_entry IS DISTINCT FROM OLD.risk_percent_per_entry
               OR NEW.risk_unit_usd IS DISTINCT FROM OLD.risk_unit_usd
               OR NEW.max_campaign_risk_usd IS DISTINCT FROM OLD.max_campaign_risk_usd
               OR NEW.locked_at IS DISTINCT FROM OLD.locked_at
            THEN
                RAISE EXCEPTION '5S-CR campaign risk lock economics are immutable'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_campaign_risk_lock_immutable_v1';
            END IF;
            IF NEW.state = OLD.state THEN
                IF NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION '5S-CR campaign risk lock cannot mutate without closure'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_campaign_risk_lock_transition_v1';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.state <> 'ACTIVE' OR NEW.state <> 'CLOSED' OR NEW.closed_at IS NULL THEN
                RAISE EXCEPTION 'invalid 5S-CR campaign risk lock transition'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_campaign_risk_lock_transition_v1';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_5scr_campaign_risk_lock_update_v1
        BEFORE UPDATE ON strategy_5scr_campaign_risk_locks
        FOR EACH ROW EXECUTE FUNCTION enforce_5scr_campaign_risk_lock_update_v1()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_5scr_risk_reservation_update_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.reservation_id IS DISTINCT FROM OLD.reservation_id
               OR NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
               OR NEW.tradeplan_id IS DISTINCT FROM OLD.tradeplan_id
               OR NEW.executor_id IS DISTINCT FROM OLD.executor_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.account_snapshot_id IS DISTINCT FROM OLD.account_snapshot_id
               OR NEW.source_candidate_hash IS DISTINCT FROM OLD.source_candidate_hash
               OR NEW.signal_id IS DISTINCT FROM OLD.signal_id
               OR NEW.signal_hash IS DISTINCT FROM OLD.signal_hash
               OR NEW.policy_id IS DISTINCT FROM OLD.policy_id
               OR NEW.canonical_symbol IS DISTINCT FROM OLD.canonical_symbol
               OR NEW.broker_symbol IS DISTINCT FROM OLD.broker_symbol
               OR NEW.entry_role IS DISTINCT FROM OLD.entry_role
               OR NEW.direction IS DISTINCT FROM OLD.direction
               OR NEW.volume IS DISTINCT FROM OLD.volume
               OR NEW.entry_price IS DISTINCT FROM OLD.entry_price
               OR NEW.stop_loss IS DISTINCT FROM OLD.stop_loss
               OR NEW.take_profit IS DISTINCT FROM OLD.take_profit
               OR NEW.risk_unit_usd IS DISTINCT FROM OLD.risk_unit_usd
               OR NEW.reserved_risk_usd IS DISTINCT FROM OLD.reserved_risk_usd
               OR NEW.balance_snapshot IS DISTINCT FROM OLD.balance_snapshot
               OR NEW.equity_snapshot IS DISTINCT FROM OLD.equity_snapshot
               OR NEW.reserved_at IS DISTINCT FROM OLD.reserved_at
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
            THEN
                RAISE EXCEPTION '5S-CR reservation economic identity is immutable'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_risk_reservation_immutable_v1';
            END IF;
            IF NEW.state = OLD.state THEN
                IF NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION '5S-CR reservation cannot mutate without a state transition'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_risk_reservation_transition_v1';
                END IF;
                RETURN NEW;
            END IF;
            IF NOT (
                (OLD.state = 'HELD' AND NEW.state IN ('CONSUMED', 'RELEASED', 'EXPIRED')) OR
                (OLD.state = 'CONSUMED' AND NEW.state IN ('OPEN', 'RELEASED')) OR
                (OLD.state = 'OPEN' AND NEW.state = 'RELEASED')
            ) THEN
                RAISE EXCEPTION 'invalid 5S-CR reservation state transition'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_risk_reservation_transition_v1';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_5scr_risk_reservation_update_v1
        BEFORE UPDATE ON strategy_5scr_risk_reservations
        FOR EACH ROW EXECUTE FUNCTION enforce_5scr_risk_reservation_update_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_5scr_final_signal_outbox_update_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.outbox_id IS DISTINCT FROM OLD.outbox_id
               OR NEW.reservation_id IS DISTINCT FROM OLD.reservation_id
               OR NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
               OR NEW.tradeplan_id IS DISTINCT FROM OLD.tradeplan_id
               OR NEW.executor_id IS DISTINCT FROM OLD.executor_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.account_snapshot_id IS DISTINCT FROM OLD.account_snapshot_id
               OR NEW.canonical_symbol IS DISTINCT FROM OLD.canonical_symbol
               OR NEW.broker_symbol IS DISTINCT FROM OLD.broker_symbol
               OR NEW.direction IS DISTINCT FROM OLD.direction
               OR NEW.signal_id IS DISTINCT FROM OLD.signal_id
               OR NEW.payload IS DISTINCT FROM OLD.payload
               OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION '5S-CR final-signal outbox identity is immutable'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_final_signal_outbox_immutable_v1';
            END IF;
            IF NEW.status = OLD.status AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION '5S-CR final-signal outbox cannot mutate without a state transition'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_final_signal_outbox_transition_v1';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                (OLD.status = 'PENDING' AND NEW.status IN ('CLAIMED', 'DEAD')) OR
                (OLD.status = 'CLAIMED' AND NEW.status IN ('PENDING', 'PUBLISHED', 'DEAD'))
            ) THEN
                RAISE EXCEPTION 'invalid 5S-CR final-signal outbox state transition'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_5scr_final_signal_outbox_transition_v1';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_5scr_final_signal_outbox_update_v1
        BEFORE UPDATE ON strategy_5scr_final_signal_outbox
        FOR EACH ROW EXECUTE FUNCTION enforce_5scr_final_signal_outbox_update_v1()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM strategy_5scr_campaign_risk_locks)
               OR EXISTS (SELECT 1 FROM strategy_5scr_risk_reservations)
               OR EXISTS (SELECT 1 FROM strategy_5scr_final_signal_outbox)
            THEN
                RAISE EXCEPTION 'remove durable 5S-CR risk authority rows before downgrade';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER trg_5scr_final_signal_outbox_update_v1 ON strategy_5scr_final_signal_outbox")
    op.execute("DROP FUNCTION enforce_5scr_final_signal_outbox_update_v1()")
    op.execute("DROP TRIGGER trg_5scr_risk_reservation_update_v1 ON strategy_5scr_risk_reservations")
    op.execute("DROP FUNCTION enforce_5scr_risk_reservation_update_v1()")
    op.execute("DROP TRIGGER trg_5scr_campaign_risk_lock_update_v1 ON strategy_5scr_campaign_risk_locks")
    op.execute("DROP FUNCTION enforce_5scr_campaign_risk_lock_update_v1()")
    op.drop_index("ix_5scr_final_signal_outbox_delivery", table_name="strategy_5scr_final_signal_outbox")
    op.drop_table("strategy_5scr_final_signal_outbox")
    op.drop_index("uq_5scr_risk_reservation_active_parent", table_name="strategy_5scr_risk_reservations")
    op.drop_index("ix_5scr_risk_reservations_campaign_state", table_name="strategy_5scr_risk_reservations")
    op.drop_index("ix_5scr_risk_reservations_account_state", table_name="strategy_5scr_risk_reservations")
    op.drop_table("strategy_5scr_risk_reservations")
    op.drop_index("ix_5scr_campaign_risk_locks_account_state", table_name="strategy_5scr_campaign_risk_locks")
    op.drop_table("strategy_5scr_campaign_risk_locks")
