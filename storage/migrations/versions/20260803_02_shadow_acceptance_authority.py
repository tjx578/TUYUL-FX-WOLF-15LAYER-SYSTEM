"""Add fail-closed lineage for SHADOW acceptance commands.

Revision ID: 20260803_02
Revises: 20260803_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_02"
down_revision = "20260803_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_commands",
        sa.Column("source_event", sa.String(length=32), nullable=False, server_default="signal_json"),
    )
    op.add_column("execution_commands", sa.Column("acceptance_run_id", sa.String(length=64), nullable=True))
    op.add_column("execution_commands", sa.Column("operator_authority", sa.String(length=80), nullable=True))
    op.add_column("execution_commands", sa.Column("acceptance_purpose", sa.String(length=80), nullable=True))
    op.alter_column("execution_commands", "source_signal_id", existing_type=sa.String(length=200), nullable=True)
    op.alter_column("execution_commands", "source_signal_hash", existing_type=sa.String(length=80), nullable=True)

    op.create_check_constraint(
        "ck_execution_command_lineage_v1",
        "execution_commands",
        """
        (
            source_event = 'signal_json'
            AND source_signal_id IS NOT NULL
            AND source_signal_hash IS NOT NULL
            AND acceptance_run_id IS NULL
            AND operator_authority IS NULL
            AND acceptance_purpose IS NULL
        )
        OR
        (
            source_event = 'SHADOW_ACCEPTANCE'
            AND source_signal_id IS NULL
            AND source_signal_hash IS NULL
            AND acceptance_run_id IS NOT NULL
            AND acceptance_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$'
            AND operator_authority = 'WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1'
            AND acceptance_purpose = 'BROKER_CONNECTED_SHADOW_VALIDATION'
        )
        """,
    )
    op.create_check_constraint(
        "ck_execution_command_payload_lineage_v1",
        "execution_commands",
        """
        (
            source_event = 'signal_json'
            AND payload #>> '{source,source_event}' = 'signal_json'
            AND payload #>> '{source,source_signal_id}' = source_signal_id
            AND payload #>> '{source,source_signal_hash}' = source_signal_hash
        )
        OR
        (
            source_event = 'SHADOW_ACCEPTANCE'
            AND payload #>> '{source,source_event}' = 'SHADOW_ACCEPTANCE'
            AND payload #>> '{source,source_schema_version}' = 'wolf15.mt5.shadow-acceptance.v1'
            AND payload #>> '{source,acceptance_run_id}' = acceptance_run_id
            AND payload #>> '{source,operator_authority}' = operator_authority
            AND payload #>> '{source,purpose}' = acceptance_purpose
            AND payload #>> '{source,phase}' IN ('A1', 'A2')
            AND length(payload #>> '{source,canonical_symbol}') >= 3
            AND length(payload #>> '{source,broker_symbol}') >= 1
            AND payload #>> '{source,execution_authority}' = 'false'
            AND payload #>> '{source,broker_execution}' = 'FORBIDDEN'
            AND payload #>> '{executor_binding,executor_id}' = executor_id::text
            AND payload #>> '{executor_binding,account_id}' = account_id
            AND payload #>> '{executor_binding,execution_mode}' = 'SHADOW'
            AND payload #>> '{action}' = 'RECONCILE_ONLY'
            AND payload -> 'order' = 'null'::jsonb
            AND not_before = issued_at
            AND expires_at <= issued_at + interval '15 minutes'
            AND (payload #>> '{issued_at_utc}')::timestamptz = issued_at
            AND (payload #>> '{not_before_utc}')::timestamptz = not_before
            AND (payload #>> '{expires_at_utc}')::timestamptz = expires_at
            AND payload #>> '{guards,guard_type}' = 'SHADOW_ACCEPTANCE'
            AND payload #>> '{guards,kill_switch_required}' = 'true'
            AND payload #>> '{guards,broker_execution}' = 'FORBIDDEN'
            AND NOT (payload -> 'guards' ? 'risk_reservation_id')
            AND NOT (payload -> 'guards' ? 'risk_snapshot_id')
        )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_execution_command_acceptance_symbol
        ON execution_commands (
            acceptance_run_id,
            ((payload #>> '{source,canonical_symbol}'))
        )
        WHERE source_event = 'SHADOW_ACCEPTANCE'
        """
    )
    op.create_index(
        "ix_execution_commands_acceptance_run",
        "execution_commands",
        ["acceptance_run_id", "state"],
        postgresql_where=sa.text("source_event = 'SHADOW_ACCEPTANCE'"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_shadow_acceptance_report_broker_effects_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_source_event text;
        BEGIN
            SELECT source_event
            INTO parent_source_event
            FROM execution_commands
            WHERE command_id = NEW.command_id;

            IF parent_source_event = 'SHADOW_ACCEPTANCE' AND (
                NEW.state NOT IN ('WOULD_EXECUTE', 'WOULD_REJECT')
                OR NEW.payload #>> '{state}' IS DISTINCT FROM NEW.state
                OR COALESCE((NEW.payload #>> '{execution,filled_volume}')::numeric, -1) <> 0
                OR NEW.payload #> '{broker,order_ticket}' IS DISTINCT FROM 'null'::jsonb
                OR NEW.payload #> '{broker,deal_ticket}' IS DISTINCT FROM 'null'::jsonb
                OR NEW.payload #> '{broker,position_id}' IS DISTINCT FROM 'null'::jsonb
            ) THEN
                RAISE EXCEPTION 'SHADOW_ACCEPTANCE reports must prove zero broker effects'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_shadow_acceptance_report_broker_forbidden_v1';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_shadow_acceptance_report_broker_forbidden_v1
        BEFORE INSERT OR UPDATE ON execution_reports
        FOR EACH ROW
        EXECUTE FUNCTION reject_shadow_acceptance_report_broker_effects_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_shadow_acceptance_broker_entity_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM execution_commands
                WHERE command_id = NEW.command_id
                  AND source_event = 'SHADOW_ACCEPTANCE'
            ) THEN
                RAISE EXCEPTION 'SHADOW_ACCEPTANCE commands cannot own broker entities'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_shadow_acceptance_broker_entity_forbidden_v1';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_shadow_acceptance_broker_entity_forbidden_v1
        BEFORE INSERT OR UPDATE ON broker_entities
        FOR EACH ROW
        EXECUTE FUNCTION reject_shadow_acceptance_broker_entity_v1()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM execution_commands
                WHERE source_event = 'SHADOW_ACCEPTANCE'
            ) THEN
                RAISE EXCEPTION 'remove SHADOW_ACCEPTANCE commands before downgrade';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER trg_shadow_acceptance_broker_entity_forbidden_v1 ON broker_entities")
    op.execute("DROP FUNCTION reject_shadow_acceptance_broker_entity_v1()")
    op.execute("DROP TRIGGER trg_shadow_acceptance_report_broker_forbidden_v1 ON execution_reports")
    op.execute("DROP FUNCTION reject_shadow_acceptance_report_broker_effects_v1()")
    op.drop_index("ix_execution_commands_acceptance_run", table_name="execution_commands")
    op.execute("DROP INDEX uq_execution_command_acceptance_symbol")
    op.drop_constraint("ck_execution_command_payload_lineage_v1", "execution_commands", type_="check")
    op.drop_constraint("ck_execution_command_lineage_v1", "execution_commands", type_="check")
    op.alter_column("execution_commands", "source_signal_hash", existing_type=sa.String(length=80), nullable=False)
    op.alter_column("execution_commands", "source_signal_id", existing_type=sa.String(length=200), nullable=False)
    op.drop_column("execution_commands", "acceptance_purpose")
    op.drop_column("execution_commands", "operator_authority")
    op.drop_column("execution_commands", "acceptance_run_id")
    op.drop_column("execution_commands", "source_event")
