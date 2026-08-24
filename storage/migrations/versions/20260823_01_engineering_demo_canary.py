"""Add fail-closed lineage and one-shot scope for D0 engineering DEMO.

Revision ID: 20260823_01
Revises: 20260822_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260823_01"
down_revision = "20260822_01"
branch_labels = None
depends_on = None


def _create_lineage_constraints_v2() -> None:
    op.create_check_constraint(
        "ck_execution_command_lineage_v2",
        "execution_commands",
        """
        (
            source_event = 'signal_json'
            AND source_signal_id IS NOT NULL
            AND source_signal_hash IS NOT NULL
            AND acceptance_run_id IS NULL
            AND operator_authority IS NULL
            AND acceptance_purpose IS NULL
            AND engineering_canary_id IS NULL
            AND canary_operator_authority IS NULL
            AND canary_purpose IS NULL
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
            AND engineering_canary_id IS NULL
            AND canary_operator_authority IS NULL
            AND canary_purpose IS NULL
        )
        OR
        (
            source_event = 'ENGINEERING_DEMO_CANARY'
            AND source_signal_id IS NULL
            AND source_signal_hash IS NULL
            AND acceptance_run_id IS NULL
            AND operator_authority IS NULL
            AND acceptance_purpose IS NULL
            AND engineering_canary_id IS NOT NULL
            AND engineering_canary_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$'
            AND canary_operator_authority = 'WOLF15_ENGINEERING_DEMO_OPERATOR_V1'
            AND canary_purpose = 'EXECUTION_PLUMBING_VALIDATION'
        )
        """,
    )
    op.create_check_constraint(
        "ck_execution_command_payload_lineage_v2",
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
        OR
        (
            source_event = 'ENGINEERING_DEMO_CANARY'
            AND payload #>> '{source,source_event}' = 'ENGINEERING_DEMO_CANARY'
            AND payload #>> '{source,source_schema_version}' = 'wolf15.mt5.engineering-demo-canary.v1'
            AND payload #>> '{source,command_source_class}' = 'ENGINEERING_DEMO_CANARY'
            AND payload #>> '{source,canary_id}' = engineering_canary_id
            AND payload #>> '{source,operator_authority}' = canary_operator_authority
            AND payload #>> '{source,purpose}' = canary_purpose
            AND payload #>> '{source,approved_executor_id}' = executor_id::text
            AND payload #>> '{source,approved_account_id}' = account_id
            AND payload #>> '{source,approved_broker_server}' = payload #>> '{executor_binding,broker_server}'
            AND payload #>> '{source,approved_canonical_symbol}' = payload #>> '{order,canonical_symbol}'
            AND payload #>> '{source,approved_broker_symbol}' = payload #>> '{order,broker_symbol}'
            AND payload #>> '{source,order_role}' = 'PARENT'
            AND payload #>> '{source,max_broker_effects}' = '1'
            AND payload #>> '{source,strategy_authority}' = 'false'
            AND payload #>> '{source,strategy_scorecard_eligible}' = 'false'
            AND payload #>> '{source,research_result_eligible}' = 'false'
            AND payload #>> '{source,live_real_money_allowed}' = 'false'
            AND payload #>> '{source,demo_only}' = 'true'
            AND payload #>> '{executor_binding,executor_id}' = executor_id::text
            AND payload #>> '{executor_binding,account_id}' = account_id
            AND payload #>> '{executor_binding,execution_mode}' = 'DEMO'
            AND payload #>> '{action}' = 'PLACE_MARKET'
            AND payload #>> '{order,side}' IN ('BUY', 'SELL')
            AND payload #>> '{order,order_type}' = payload #>> '{order,side}'
            AND payload #>> '{order,comment_tag}' LIKE 'W15D0:%'
            AND payload #>> '{order,magic}' = '150016'
            AND payload #>> '{order,time_in_force}' = 'GTC'
            AND (payload -> 'order' -> 'broker_expiration_utc')
                IS NOT DISTINCT FROM 'null'::jsonb
            AND (payload #>> '{order,stop_loss}')::numeric > 0
            AND (payload #>> '{order,take_profit}')::numeric > 0
            AND payload #>> '{guards,guard_type}' = 'ENGINEERING_DEMO_CANARY'
            AND payload #>> '{guards,scoped_demo_window_required}' = 'true'
            AND payload #>> '{guards,broker_ledger_reconciled}' = 'true'
            AND payload #>> '{guards,require_attached_sl}' = 'true'
            AND payload #>> '{guards,require_attached_tp}' = 'true'
            AND payload #>> '{guards,max_submit_attempts}' = '1'
            AND payload #>> '{guards,max_broker_effects}' = '1'
            AND payload #>> '{guards,allow_volume_round_down}' = 'false'
            AND payload #>> '{guards,allow_price_normalization}' = 'false'
            AND payload #>> '{guards,broker_execution}' = 'DEMO_ONLY'
            AND NOT (payload -> 'guards' ? 'risk_reservation_id')
            AND NOT (payload -> 'guards' ? 'risk_snapshot_id')
            AND risk_reservation_id IS NULL
            AND risk_snapshot_id IS NULL
            AND not_before = issued_at
            AND expires_at <= issued_at + interval '2 minutes'
            AND (payload #>> '{issued_at_utc}')::timestamptz = issued_at
            AND (payload #>> '{not_before_utc}')::timestamptz = not_before
            AND (payload #>> '{expires_at_utc}')::timestamptz = expires_at
        )
        """,
    )


def upgrade() -> None:
    op.add_column("execution_commands", sa.Column("engineering_canary_id", sa.String(length=64), nullable=True))
    op.add_column(
        "execution_commands",
        sa.Column("canary_operator_authority", sa.String(length=80), nullable=True),
    )
    op.add_column("execution_commands", sa.Column("canary_purpose", sa.String(length=80), nullable=True))

    op.drop_constraint("ck_execution_command_payload_lineage_v1", "execution_commands", type_="check")
    op.drop_constraint("ck_execution_command_lineage_v1", "execution_commands", type_="check")
    _create_lineage_constraints_v2()

    op.create_index(
        "uq_execution_command_engineering_canary",
        "execution_commands",
        ["engineering_canary_id"],
        unique=True,
        postgresql_where=sa.text("source_event = 'ENGINEERING_DEMO_CANARY'"),
    )
    op.create_index(
        "ix_execution_commands_engineering_canary_state",
        "execution_commands",
        ["engineering_canary_id", "state"],
        postgresql_where=sa.text("source_event = 'ENGINEERING_DEMO_CANARY'"),
    )

    op.create_table(
        "engineering_demo_canary_windows",
        sa.Column("canary_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "command_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("execution_commands.command_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "executor_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("executor_instances.executor_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("broker_server", sa.String(length=200), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="QUEUED"),
        sa.Column("max_broker_effects", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED','CLOSED','EXPIRED')",
            name="ck_engineering_demo_canary_window_state",
        ),
        sa.CheckConstraint("max_broker_effects = 1", name="ck_engineering_demo_canary_one_effect"),
        sa.CheckConstraint(
            "(state IN ('ARMED','RECONCILIATION_REQUIRED')) = (armed_at IS NOT NULL AND terminal_at IS NULL)",
            name="ck_engineering_demo_canary_armed_clock",
        ),
        sa.CheckConstraint(
            "(state IN ('CLOSED','EXPIRED')) = (terminal_at IS NOT NULL)",
            name="ck_engineering_demo_canary_terminal_clock",
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_engineering_demo_canary_single_open
        ON engineering_demo_canary_windows ((true))
        WHERE state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED')
        """
    )
    op.create_index(
        "ix_engineering_demo_canary_executor_state",
        "engineering_demo_canary_windows",
        ["executor_id", "state", "expires_at"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM execution_commands WHERE source_event = 'ENGINEERING_DEMO_CANARY') THEN
                RAISE EXCEPTION 'remove ENGINEERING_DEMO_CANARY commands before downgrade';
            END IF;
        END
        $$
        """
    )
    op.drop_index("ix_engineering_demo_canary_executor_state", table_name="engineering_demo_canary_windows")
    op.execute("DROP INDEX uq_engineering_demo_canary_single_open")
    op.drop_table("engineering_demo_canary_windows")
    op.drop_index("ix_execution_commands_engineering_canary_state", table_name="execution_commands")
    op.drop_index("uq_execution_command_engineering_canary", table_name="execution_commands")
    op.drop_constraint("ck_execution_command_payload_lineage_v2", "execution_commands", type_="check")
    op.drop_constraint("ck_execution_command_lineage_v2", "execution_commands", type_="check")

    op.create_check_constraint(
        "ck_execution_command_lineage_v1",
        "execution_commands",
        """
        (source_event = 'signal_json' AND source_signal_id IS NOT NULL AND source_signal_hash IS NOT NULL
         AND acceptance_run_id IS NULL AND operator_authority IS NULL AND acceptance_purpose IS NULL)
        OR
        (source_event = 'SHADOW_ACCEPTANCE' AND source_signal_id IS NULL AND source_signal_hash IS NULL
         AND acceptance_run_id IS NOT NULL AND acceptance_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$'
         AND operator_authority = 'WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1'
         AND acceptance_purpose = 'BROKER_CONNECTED_SHADOW_VALIDATION')
        """,
    )
    op.create_check_constraint(
        "ck_execution_command_payload_lineage_v1",
        "execution_commands",
        """
        (source_event = 'signal_json'
         AND payload #>> '{source,source_event}' = 'signal_json'
         AND payload #>> '{source,source_signal_id}' = source_signal_id
         AND payload #>> '{source,source_signal_hash}' = source_signal_hash)
        OR
        (source_event = 'SHADOW_ACCEPTANCE'
         AND payload #>> '{source,source_event}' = 'SHADOW_ACCEPTANCE'
         AND payload #>> '{source,source_schema_version}' = 'wolf15.mt5.shadow-acceptance.v1'
         AND payload #>> '{source,acceptance_run_id}' = acceptance_run_id
         AND payload #>> '{source,operator_authority}' = operator_authority
         AND payload #>> '{source,purpose}' = acceptance_purpose
         AND payload #>> '{source,phase}' IN ('A1','A2')
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
         AND NOT (payload -> 'guards' ? 'risk_snapshot_id'))
        """,
    )
    op.drop_column("execution_commands", "canary_purpose")
    op.drop_column("execution_commands", "canary_operator_authority")
    op.drop_column("execution_commands", "engineering_canary_id")
