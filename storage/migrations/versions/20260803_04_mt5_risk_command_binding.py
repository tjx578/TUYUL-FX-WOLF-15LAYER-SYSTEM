"""Bind risk-authorized final signals to SHADOW MT5 commands atomically.

Revision ID: 20260803_04
Revises: 20260803_03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260803_04"
down_revision = "20260803_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # C1 introduced reservation.command_id -> execution_commands while C2
    # introduces the inverse authority binding.  Both sides must be deferred
    # NO ACTION constraints: RESTRICT is checked immediately by PostgreSQL and
    # would make the otherwise valid authority pair impossible to remove in a
    # single transaction.
    op.drop_constraint(
        "strategy_5scr_risk_reservations_command_id_fkey",
        "strategy_5scr_risk_reservations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_5scr_risk_reservation_command_v2",
        "strategy_5scr_risk_reservations",
        "execution_commands",
        ["command_id"],
        ["command_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.add_column(
        "execution_commands",
        sa.Column("risk_reservation_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "execution_commands",
        sa.Column("risk_snapshot_id", sa.String(length=200), nullable=True),
    )
    op.create_unique_constraint(
        "uq_5scr_reservation_command_binding_v1",
        "strategy_5scr_risk_reservations",
        [
            "reservation_id",
            "command_id",
            "executor_id",
            "account_id",
            "signal_id",
            "signal_hash",
            "account_snapshot_id",
        ],
    )
    op.create_foreign_key(
        "fk_execution_command_risk_reservation_v1",
        "execution_commands",
        "strategy_5scr_risk_reservations",
        [
            "risk_reservation_id",
            "command_id",
            "executor_id",
            "account_id",
            "source_signal_id",
            "source_signal_hash",
            "risk_snapshot_id",
        ],
        [
            "reservation_id",
            "command_id",
            "executor_id",
            "account_id",
            "signal_id",
            "signal_hash",
            "account_snapshot_id",
        ],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "uq_execution_command_risk_reservation_v1",
        "execution_commands",
        ["risk_reservation_id"],
        unique=True,
        postgresql_where=sa.text("risk_reservation_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_execution_command_risk_authority_v1",
        "execution_commands",
        """
        (
            source_event = 'signal_json'
            AND payload #>> '{source,source_schema_version}' =
                'wolf15.strategy-5scr.final-signal.v1'
            AND risk_reservation_id IS NOT NULL
            AND risk_snapshot_id IS NOT NULL
            AND source_signal_id IS NOT NULL
            AND source_signal_hash IS NOT NULL
            AND action = 'PLACE_MARKET'
            AND payload #>> '{action}' = 'PLACE_MARKET'
            AND payload #>> '{executor_binding,executor_id}' = executor_id::text
            AND payload #>> '{executor_binding,account_id}' = account_id
            AND payload #>> '{executor_binding,execution_mode}' = 'SHADOW'
            AND payload #>> '{source,source_event}' = 'signal_json'
            AND payload #>> '{source,source_signal_id}' = source_signal_id
            AND payload #>> '{source,source_signal_hash}' = source_signal_hash
            AND payload #>> '{source,block_role}' = 'PARENT'
            AND payload #>> '{guards,risk_reservation_id}' = risk_reservation_id::text
            AND payload #>> '{guards,risk_snapshot_id}' = risk_snapshot_id
            AND payload #>> '{order,side}' IN ('BUY', 'SELL')
            AND payload #>> '{order,order_type}' = payload #>> '{order,side}'
            AND payload #> '{order,broker_order_ticket}' = 'null'::jsonb
            AND payload #> '{order,broker_position_id}' = 'null'::jsonb
        )
        OR
        (
            payload #>> '{source,source_schema_version}' IS DISTINCT FROM
                'wolf15.strategy-5scr.final-signal.v1'
            AND risk_reservation_id IS NULL
            AND risk_snapshot_id IS NULL
        )
        """,
    )

    op.execute(
        """
        CREATE FUNCTION reject_shadow_report_broker_effects_v2()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_mode text;
        BEGIN
            SELECT payload #>> '{executor_binding,execution_mode}'
            INTO parent_mode
            FROM execution_commands
            WHERE command_id = NEW.command_id;

            IF parent_mode = 'SHADOW' AND (
                NEW.state NOT IN ('WOULD_EXECUTE', 'WOULD_REJECT')
                OR NEW.payload #>> '{state}' IS DISTINCT FROM NEW.state
                OR COALESCE((NEW.payload #>> '{execution,filled_volume}')::numeric, 0) <> 0
                OR COALESCE(NEW.payload #> '{broker,order_ticket}', 'null'::jsonb) <> 'null'::jsonb
                OR COALESCE(NEW.payload #> '{broker,deal_ticket}', 'null'::jsonb) <> 'null'::jsonb
                OR COALESCE(NEW.payload #> '{broker,position_id}', 'null'::jsonb) <> 'null'::jsonb
            ) THEN
                RAISE EXCEPTION 'SHADOW reports must prove zero broker effects'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_shadow_report_broker_forbidden_v2';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_shadow_report_broker_forbidden_v2
        BEFORE INSERT OR UPDATE ON execution_reports
        FOR EACH ROW
        EXECUTE FUNCTION reject_shadow_report_broker_effects_v2()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_shadow_broker_entity_v2()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM execution_commands
                WHERE command_id = NEW.command_id
                  AND payload #>> '{executor_binding,execution_mode}' = 'SHADOW'
            ) THEN
                RAISE EXCEPTION 'SHADOW commands cannot own broker entities'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_shadow_broker_entity_forbidden_v2';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_shadow_broker_entity_forbidden_v2
        BEFORE INSERT OR UPDATE ON broker_entities
        FOR EACH ROW
        EXECUTE FUNCTION reject_shadow_broker_entity_v2()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM execution_commands
                WHERE risk_reservation_id IS NOT NULL OR risk_snapshot_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'remove risk-bound execution commands before downgrade';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER trg_shadow_broker_entity_forbidden_v2 ON broker_entities")
    op.execute("DROP FUNCTION reject_shadow_broker_entity_v2()")
    op.execute("DROP TRIGGER trg_shadow_report_broker_forbidden_v2 ON execution_reports")
    op.execute("DROP FUNCTION reject_shadow_report_broker_effects_v2()")
    op.drop_constraint("ck_execution_command_risk_authority_v1", "execution_commands", type_="check")
    op.drop_index("uq_execution_command_risk_reservation_v1", table_name="execution_commands")
    op.drop_constraint("fk_execution_command_risk_reservation_v1", "execution_commands", type_="foreignkey")
    op.drop_constraint(
        "fk_5scr_risk_reservation_command_v2",
        "strategy_5scr_risk_reservations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "strategy_5scr_risk_reservations_command_id_fkey",
        "strategy_5scr_risk_reservations",
        "execution_commands",
        ["command_id"],
        ["command_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_5scr_reservation_command_binding_v1",
        "strategy_5scr_risk_reservations",
        type_="unique",
    )
    op.drop_column("execution_commands", "risk_snapshot_id")
    op.drop_column("execution_commands", "risk_reservation_id")
