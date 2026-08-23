"""Bind one C2 SHADOW projection to one signed C3 command.

Revision ID: 20260813_04
Revises: 20260813_03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260813_04"
down_revision = "20260813_03"
branch_labels = None
depends_on = None

PROJECTION = "strategy_5scr_shadow_risk_projections_v1"
ISSUANCE = "strategy_5scr_c3_shadow_issuances_v1"


def upgrade() -> None:
    # Projection-only columns stay NULL for every existing and future command
    # class.  They are not global defaults for eventual DEMO/LIVE semantics.
    op.add_column("execution_commands", sa.Column("operator_run_id", sa.String(length=64), nullable=True))
    op.add_column("execution_commands", sa.Column("source_shadow_authority_id", sa.Text(), nullable=True))
    op.add_column("execution_commands", sa.Column("source_candidate_id", sa.Text(), nullable=True))
    op.add_column("execution_commands", sa.Column("source_candidate_sequence", sa.Integer(), nullable=True))
    op.add_column("execution_commands", sa.Column("source_candidate_revision", sa.Integer(), nullable=True))
    op.add_column("execution_commands", sa.Column("source_account_snapshot_id", sa.String(length=200), nullable=True))
    op.add_column("execution_commands", sa.Column("execution_authority", sa.Boolean(), nullable=True))
    op.add_column("execution_commands", sa.Column("capital_reserved", sa.Boolean(), nullable=True))
    op.add_column("execution_commands", sa.Column("broker_side_effect_allowed", sa.Boolean(), nullable=True))
    op.add_column("execution_commands", sa.Column("order_send_eligible", sa.Boolean(), nullable=True))

    op.create_unique_constraint(
        "uq_5scr_shadow_projection_v1_c3_scope",
        PROJECTION,
        [
            "shadow_authority_id",
            "tradeplan_id",
            "candidate_sequence",
            "candidate_revision",
            "executor_id",
            "account_id",
            "account_snapshot_id",
        ],
    )
    op.create_foreign_key(
        "fk_execution_command_shadow_projection_v1",
        "execution_commands",
        PROJECTION,
        [
            "source_shadow_authority_id",
            "source_candidate_id",
            "source_candidate_sequence",
            "source_candidate_revision",
            "executor_id",
            "account_id",
            "source_account_snapshot_id",
        ],
        [
            "shadow_authority_id",
            "tradeplan_id",
            "candidate_sequence",
            "candidate_revision",
            "executor_id",
            "account_id",
            "account_snapshot_id",
        ],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "uq_execution_command_shadow_projection_v1",
        "execution_commands",
        ["source_shadow_authority_id"],
        unique=True,
        postgresql_where=sa.text("source_shadow_authority_id IS NOT NULL"),
    )
    op.create_index(
        "uq_execution_command_operator_run_v1",
        "execution_commands",
        ["operator_run_id"],
        unique=True,
        postgresql_where=sa.text("operator_run_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_execution_command_shadow_projection_v1",
        "execution_commands",
        """
        (
            source_shadow_authority_id IS NULL
            AND operator_run_id IS NULL
            AND source_candidate_id IS NULL
            AND source_candidate_sequence IS NULL
            AND source_candidate_revision IS NULL
            AND source_account_snapshot_id IS NULL
            AND execution_authority IS NULL
            AND capital_reserved IS NULL
            AND broker_side_effect_allowed IS NULL
            AND order_send_eligible IS NULL
            AND payload #>> '{source,source_schema_version}' IS DISTINCT FROM
                'wolf15.strategy-5scr.shadow-projection-command.v1'
        )
        OR
        (
            source_shadow_authority_id ~ '^5scr-shadow-authority-v1:[0-9a-f]{32}$'
            AND operator_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$'
            AND source_candidate_id ~ '^5scr-tradeplan-v2:[0-9a-f]{32}$'
            AND source_candidate_sequence >= 1
            AND source_candidate_revision = 1
            AND source_account_snapshot_id IS NOT NULL
            AND execution_authority IS FALSE
            AND capital_reserved IS FALSE
            AND broker_side_effect_allowed IS FALSE
            AND order_send_eligible IS FALSE
            AND source_event = 'signal_json'
            AND source_signal_id = source_shadow_authority_id
            AND risk_reservation_id IS NULL
            AND risk_snapshot_id IS NULL
            AND action = 'PLACE_MARKET'
            AND not_before = issued_at
            AND expires_at > issued_at
            AND expires_at <= issued_at + interval '300 seconds'
            AND payload #>> '{command_id}' = command_id::text
            AND payload #>> '{idempotency_key}' = idempotency_key
            AND (payload #>> '{revision}')::integer = revision
            AND payload #>> '{action}' = action
            AND payload #>> '{executor_binding,execution_mode}' = 'SHADOW'
            AND payload #>> '{executor_binding,executor_id}' = executor_id::text
            AND payload #>> '{executor_binding,account_id}' = account_id
            AND payload #>> '{source,source_schema_version}' =
                'wolf15.strategy-5scr.shadow-projection-command.v1'
            AND payload #>> '{source,source_shadow_authority_id}' = source_shadow_authority_id
            AND payload #>> '{source,source_shadow_authority_hash}' = source_signal_hash
            AND payload #>> '{source,source_candidate_id}' = source_candidate_id
            AND (payload #>> '{source,source_candidate_sequence}')::integer = source_candidate_sequence
            AND (payload #>> '{source,source_candidate_revision}')::integer = source_candidate_revision
            AND payload #>> '{source,source_admission_class}' = 'CANONICAL_CANDIDATE_V2'
            AND payload #>> '{source,execution_authority}' = 'false'
            AND payload #>> '{source,capital_reserved}' = 'false'
            AND payload #>> '{source,broker_side_effect_allowed}' = 'false'
            AND payload #>> '{source,order_send_eligible}' = 'false'
            AND payload #>> '{source,broker_execution}' = 'FORBIDDEN'
            AND payload #>> '{guards,guard_type}' = 'C2_SHADOW_PROJECTION'
            AND payload #>> '{guards,kill_switch_required}' = 'true'
            AND payload #>> '{guards,account_snapshot_id}' = source_account_snapshot_id
            AND payload #>> '{guards,execution_authority}' = 'false'
            AND payload #>> '{guards,capital_reserved}' = 'false'
            AND payload #>> '{guards,broker_side_effect_allowed}' = 'false'
            AND payload #>> '{guards,order_send_eligible}' = 'false'
            AND payload #>> '{guards,broker_execution}' = 'FORBIDDEN'
            AND payload #>> '{order,side}' IN ('BUY','SELL')
            AND payload #>> '{order,order_type}' = payload #>> '{order,side}'
            AND payload #> '{order,broker_order_ticket}' = 'null'::jsonb
            AND payload #> '{order,broker_position_id}' = 'null'::jsonb
            AND (payload #>> '{issued_at_utc}')::timestamptz = issued_at
            AND (payload #>> '{not_before_utc}')::timestamptz = not_before
            AND (payload #>> '{expires_at_utc}')::timestamptz = expires_at
            AND NOT (payload -> 'guards' ? 'risk_reservation_id')
            AND NOT (payload -> 'guards' ? 'risk_snapshot_id')
        )
        """,
    )

    op.create_table(
        ISSUANCE,
        sa.Column("command_id", UUID(as_uuid=True), nullable=False),
        sa.Column("operator_run_id", sa.String(length=64), nullable=False),
        sa.Column("operator_authority", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("source_shadow_authority_id", sa.Text(), nullable=False),
        sa.Column("source_candidate_id", sa.Text(), nullable=False),
        sa.Column("source_candidate_sequence", sa.Integer(), nullable=False),
        sa.Column("source_candidate_revision", sa.Integer(), nullable=False),
        sa.Column("executor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("account_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("governance_version", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_payload_hash", sa.String(length=71), nullable=False),
        sa.Column("command_payload_hash", sa.String(length=71), nullable=False),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capital_reserved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("broker_side_effect_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order_send_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("command_id", name="pk_5scr_c3_shadow_issuance_v1"),
        sa.UniqueConstraint("operator_run_id", name="uq_5scr_c3_shadow_issuance_v1_operator_run"),
        sa.UniqueConstraint("source_shadow_authority_id", name="uq_5scr_c3_shadow_issuance_v1_projection"),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["execution_commands.command_id"],
            name="fk_5scr_c3_shadow_issuance_v1_command",
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_shadow_authority_id",
                "source_candidate_id",
                "source_candidate_sequence",
                "source_candidate_revision",
                "executor_id",
                "account_id",
                "account_snapshot_id",
            ],
            [
                f"{PROJECTION}.shadow_authority_id",
                f"{PROJECTION}.tradeplan_id",
                f"{PROJECTION}.candidate_sequence",
                f"{PROJECTION}.candidate_revision",
                f"{PROJECTION}.executor_id",
                f"{PROJECTION}.account_id",
                f"{PROJECTION}.account_snapshot_id",
            ],
            name="fk_5scr_c3_shadow_issuance_v1_projection_scope",
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operator_authority='WOLF15_C3_SHADOW_PROJECTION_OPERATOR_V1' "
            "AND length(btrim(actor))>=2 AND length(btrim(reason))>=3 "
            "AND governance_version>=1 AND issued_at<command_expires_at "
            "AND request_payload_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND command_payload_hash ~ '^sha256:[0-9a-f]{64}$' "
            "AND jsonb_typeof(manifest)='object'",
            name="ck_5scr_c3_shadow_issuance_v1_identity",
        ),
        sa.CheckConstraint(
            "execution_authority IS FALSE AND capital_reserved IS FALSE "
            "AND broker_side_effect_allowed IS FALSE AND order_send_eligible IS FALSE",
            name="ck_5scr_c3_shadow_issuance_v1_inert",
        ),
    )

    op.execute(
        f"""
        CREATE FUNCTION strategy_5scr_guard_shadow_projection_command_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            projection_row {PROJECTION}%ROWTYPE;
            executor_row executor_instances%ROWTYPE;
            governance_row executor_bridge_governance%ROWTYPE;
            latest_snapshot_id text;
            latest_snapshot_captured_at timestamptz;
            latest_snapshot_row executor_account_snapshots%ROWTYPE;
            candidate_row strategy_5scr_tradeplan_candidates_v2%ROWTYPE;
            candidate_has_successor boolean;
        BEGIN
            IF NEW.source_shadow_authority_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF TG_OP='UPDATE' AND (
                NEW.command_id IS DISTINCT FROM OLD.command_id OR
                NEW.executor_id IS DISTINCT FROM OLD.executor_id OR
                NEW.account_id IS DISTINCT FROM OLD.account_id OR
                NEW.source_event IS DISTINCT FROM OLD.source_event OR
                NEW.source_signal_id IS DISTINCT FROM OLD.source_signal_id OR
                NEW.source_signal_hash IS DISTINCT FROM OLD.source_signal_hash OR
                NEW.acceptance_run_id IS DISTINCT FROM OLD.acceptance_run_id OR
                NEW.operator_authority IS DISTINCT FROM OLD.operator_authority OR
                NEW.acceptance_purpose IS DISTINCT FROM OLD.acceptance_purpose OR
                NEW.operator_run_id IS DISTINCT FROM OLD.operator_run_id OR
                NEW.source_shadow_authority_id IS DISTINCT FROM OLD.source_shadow_authority_id OR
                NEW.source_candidate_id IS DISTINCT FROM OLD.source_candidate_id OR
                NEW.source_candidate_sequence IS DISTINCT FROM OLD.source_candidate_sequence OR
                NEW.source_candidate_revision IS DISTINCT FROM OLD.source_candidate_revision OR
                NEW.source_account_snapshot_id IS DISTINCT FROM OLD.source_account_snapshot_id OR
                NEW.execution_authority IS DISTINCT FROM OLD.execution_authority OR
                NEW.capital_reserved IS DISTINCT FROM OLD.capital_reserved OR
                NEW.broker_side_effect_allowed IS DISTINCT FROM OLD.broker_side_effect_allowed OR
                NEW.order_send_eligible IS DISTINCT FROM OLD.order_send_eligible OR
                NEW.risk_reservation_id IS DISTINCT FROM OLD.risk_reservation_id OR
                NEW.risk_snapshot_id IS DISTINCT FROM OLD.risk_snapshot_id OR
                NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
                NEW.revision IS DISTINCT FROM OLD.revision OR
                NEW.action IS DISTINCT FROM OLD.action OR
                NEW.payload IS DISTINCT FROM OLD.payload OR
                NEW.payload_hash IS DISTINCT FROM OLD.payload_hash OR
                NEW.issued_at IS DISTINCT FROM OLD.issued_at OR
                NEW.not_before IS DISTINCT FROM OLD.not_before OR
                NEW.expires_at IS DISTINCT FROM OLD.expires_at OR
                NEW.wire_format IS DISTINCT FROM OLD.wire_format OR
                NEW.payload_encoding IS DISTINCT FROM OLD.payload_encoding OR
                NEW.signed_payload_b64 IS DISTINCT FROM OLD.signed_payload_b64 OR
                NEW.signed_payload_sha256 IS DISTINCT FROM OLD.signed_payload_sha256 OR
                NEW.signature_algorithm IS DISTINCT FROM OLD.signature_algorithm OR
                NEW.signature_key_id IS DISTINCT FROM OLD.signature_key_id OR
                NEW.signature_value IS DISTINCT FROM OLD.signature_value OR
                NEW.created_at IS DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION 'C3 SHADOW projection command lineage is immutable'
                    USING ERRCODE='23514', CONSTRAINT='ck_execution_command_shadow_projection_immutable_v1';
            END IF;
            -- Only lifecycle fields (state, claim/lease, report cursor,
            -- terminal_at and updated_at) may advance after INSERT.  They must
            -- not be coupled to a later heartbeat or kill-switch transition.
            IF TG_OP='UPDATE' THEN
                RETURN NEW;
            END IF;
            SELECT * INTO projection_row FROM {PROJECTION}
            WHERE shadow_authority_id=NEW.source_shadow_authority_id FOR SHARE;
            IF NOT FOUND OR projection_row.state<>'COMMAND_ISSUED'
               OR projection_row.decision<>'WOULD_RESERVE'
               OR projection_row.source_admission_class<>'CANONICAL_CANDIDATE_V2'
               OR projection_row.kill_switch_observed<>'ENGAGED'
               OR projection_row.expires_at<=clock_timestamp()
               OR NEW.issued_at<projection_row.projected_at
               OR NEW.expires_at>projection_row.expires_at
               OR projection_row.execution_authority OR projection_row.capital_reserved
               OR projection_row.broker_side_effect_allowed OR projection_row.order_send_eligible
               OR NEW.source_signal_hash IS DISTINCT FROM projection_row.authority_hash
               OR NEW.payload #>> '{{source,source_candidate_material_hash}}'
                    IS DISTINCT FROM projection_row.material_candidate_hash
               OR NEW.payload #>> '{{source,source_candidate_evidence_hash}}'
                    IS DISTINCT FROM projection_row.candidate_evidence_hash
               OR NEW.payload #>> '{{source,strategy_proof_hash}}'
                    IS DISTINCT FROM projection_row.evidence_hash
               OR NEW.payload #>> '{{order,canonical_symbol}}' IS DISTINCT FROM projection_row.symbol
               OR NEW.payload #>> '{{order,broker_symbol}}' IS DISTINCT FROM projection_row.broker_symbol
               OR NEW.payload #>> '{{order,side}}' IS DISTINCT FROM projection_row.direction
               OR (NEW.payload #>> '{{order,volume}}')::numeric IS DISTINCT FROM projection_row.would_volume
               OR (NEW.payload #>> '{{order,entry_price}}')::numeric IS DISTINCT FROM projection_row.entry_price
               OR (NEW.payload #>> '{{order,stop_loss}}')::numeric IS DISTINCT FROM projection_row.stop_loss
               OR (NEW.payload #>> '{{order,take_profit}}')::numeric IS DISTINCT FROM projection_row.target_price THEN
                RAISE EXCEPTION 'C3 command lacks consumed inert SHADOW projection authority'
                    USING ERRCODE='23514', CONSTRAINT='ck_execution_command_shadow_projection_authority_v1';
            END IF;
            SELECT * INTO candidate_row FROM strategy_5scr_tradeplan_candidates_v2
            WHERE tradeplan_id=projection_row.tradeplan_id FOR SHARE;
            PERFORM 1 FROM strategy_5scr_tradeplan_candidates_v2
            WHERE previous_tradeplan_id=projection_row.tradeplan_id FOR SHARE;
            candidate_has_successor := FOUND;
            SELECT * INTO executor_row FROM executor_instances WHERE executor_id=NEW.executor_id FOR SHARE;
            SELECT * INTO governance_row FROM executor_bridge_governance WHERE singleton_id=1 FOR SHARE;
            LOCK TABLE executor_account_snapshots IN SHARE MODE;
            SELECT * INTO latest_snapshot_row FROM executor_account_snapshots WHERE executor_id=NEW.executor_id
            ORDER BY captured_at DESC LIMIT 1 FOR SHARE;
            latest_snapshot_id := latest_snapshot_row.snapshot_id;
            latest_snapshot_captured_at := latest_snapshot_row.captured_at;
            IF executor_row.account_id IS DISTINCT FROM NEW.account_id
               OR executor_row.execution_mode<>'SHADOW' OR executor_row.revoked_at IS NOT NULL
               OR executor_row.status<>'ONLINE'
               OR executor_row.broker_server IS DISTINCT FROM projection_row.broker_server
               OR NEW.payload #>> '{{executor_binding,login_hash}}' IS DISTINCT FROM executor_row.login_hash
               OR NEW.payload #>> '{{executor_binding,broker_server}}'
                    IS DISTINCT FROM projection_row.broker_server
               OR candidate_row.tradeplan_id IS NULL
               OR candidate_row.candidate_status<>'TRADEPLAN_CANDIDATE'
               OR candidate_row.lifecycle_state<>'ACTIVE'
               OR candidate_row.candidate_sequence IS DISTINCT FROM projection_row.candidate_sequence
               OR candidate_row.candidate_revision IS DISTINCT FROM projection_row.candidate_revision
               OR candidate_row.material_candidate_hash IS DISTINCT FROM projection_row.material_candidate_hash
               OR candidate_row.formation_evidence_hash IS DISTINCT FROM projection_row.candidate_evidence_hash
               OR candidate_has_successor
               OR NOT governance_row.kill_switch_active
               OR (NEW.payload #>> '{{guards,observed_governance_version}}')::bigint
                    IS DISTINCT FROM governance_row.governance_version
               OR latest_snapshot_id IS DISTINCT FROM projection_row.account_snapshot_id
               OR (NEW.payload #>> '{{guards,balance_snapshot}}')::numeric
                    IS DISTINCT FROM latest_snapshot_row.balance
               OR (NEW.payload #>> '{{guards,equity_snapshot}}')::numeric
                    IS DISTINCT FROM latest_snapshot_row.equity
               OR NEW.payload #>> '{{guards,expected_margin_mode}}'
                    IS DISTINCT FROM latest_snapshot_row.margin_mode
               OR latest_snapshot_captured_at<clock_timestamp()-interval '30 seconds'
               OR latest_snapshot_captured_at>clock_timestamp()+interval '2 seconds' THEN
                RAISE EXCEPTION 'C3 SHADOW executor/governance/snapshot binding is stale'
                    USING ERRCODE='23514', CONSTRAINT='ck_execution_command_shadow_projection_runtime_v1';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_shadow_projection_command_v1
        BEFORE INSERT OR UPDATE ON execution_commands
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_shadow_projection_command_v1();

        CREATE FUNCTION strategy_5scr_reject_c3_shadow_issuance_mutation_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'C3 SHADOW issuance audit is append-only'
                USING ERRCODE='23514', CONSTRAINT='ck_5scr_c3_shadow_issuance_v1_immutable';
        END $$;
        CREATE TRIGGER trg_5scr_c3_shadow_issuance_immutable_v1
        BEFORE UPDATE OR DELETE ON {ISSUANCE}
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_reject_c3_shadow_issuance_mutation_v1();

        CREATE FUNCTION strategy_5scr_guard_c3_shadow_issuance_insert_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            command_row execution_commands%ROWTYPE;
            projection_state text;
        BEGIN
            SELECT * INTO command_row FROM execution_commands WHERE command_id=NEW.command_id;
            SELECT state INTO projection_state FROM {PROJECTION}
            WHERE shadow_authority_id=NEW.source_shadow_authority_id;
            IF NOT FOUND OR projection_state<>'COMMAND_ISSUED'
               OR command_row.source_shadow_authority_id IS DISTINCT FROM NEW.source_shadow_authority_id
               OR command_row.operator_run_id IS DISTINCT FROM NEW.operator_run_id
               OR command_row.source_candidate_id IS DISTINCT FROM NEW.source_candidate_id
               OR command_row.source_candidate_sequence IS DISTINCT FROM NEW.source_candidate_sequence
               OR command_row.source_candidate_revision IS DISTINCT FROM NEW.source_candidate_revision
               OR command_row.executor_id IS DISTINCT FROM NEW.executor_id
               OR command_row.account_id IS DISTINCT FROM NEW.account_id
               OR command_row.source_account_snapshot_id IS DISTINCT FROM NEW.account_snapshot_id
               OR command_row.payload_hash IS DISTINCT FROM NEW.command_payload_hash THEN
                RAISE EXCEPTION 'C3 SHADOW issuance does not match command/projection lineage'
                    USING ERRCODE='23514', CONSTRAINT='ck_5scr_c3_shadow_issuance_v1_scope';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_5scr_guard_c3_shadow_issuance_insert_v1
        BEFORE INSERT ON {ISSUANCE}
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_c3_shadow_issuance_insert_v1();

        CREATE FUNCTION strategy_5scr_require_c3_shadow_issuance_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.source_shadow_authority_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM {ISSUANCE} issuance
                WHERE issuance.command_id=NEW.command_id
                  AND issuance.operator_run_id=NEW.operator_run_id
                  AND issuance.source_shadow_authority_id=NEW.source_shadow_authority_id
            ) THEN
                RAISE EXCEPTION 'projection command requires atomic C3 issuance audit'
                    USING ERRCODE='23514', CONSTRAINT='fk_execution_command_c3_issuance_v1';
            END IF;
            RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER trg_5scr_require_c3_shadow_issuance_v1
        AFTER INSERT OR UPDATE ON execution_commands
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_require_c3_shadow_issuance_v1();

        CREATE FUNCTION strategy_5scr_require_c3_shadow_command_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.state='COMMAND_ISSUED' AND NOT EXISTS (
                SELECT 1 FROM {ISSUANCE} issuance
                JOIN execution_commands command ON command.command_id=issuance.command_id
                WHERE issuance.source_shadow_authority_id=NEW.shadow_authority_id
                  AND command.source_shadow_authority_id=NEW.shadow_authority_id
            ) THEN
                RAISE EXCEPTION 'consumed projection requires atomic C3 command and issuance'
                    USING ERRCODE='23514', CONSTRAINT='fk_5scr_shadow_projection_c3_command_v1';
            END IF;
            RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER trg_5scr_require_c3_shadow_command_v1
        AFTER INSERT OR UPDATE ON {PROJECTION}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION strategy_5scr_require_c3_shadow_command_v1();
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM {ISSUANCE}) OR EXISTS (
                SELECT 1 FROM execution_commands WHERE source_shadow_authority_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'remove C3 SHADOW projection commands and issuances before downgrade';
            END IF;
        END $$;
        """
    )
    op.execute(f"DROP TRIGGER trg_5scr_require_c3_shadow_command_v1 ON {PROJECTION}")
    op.execute("DROP FUNCTION strategy_5scr_require_c3_shadow_command_v1()")
    op.execute("DROP TRIGGER trg_5scr_require_c3_shadow_issuance_v1 ON execution_commands")
    op.execute("DROP FUNCTION strategy_5scr_require_c3_shadow_issuance_v1()")
    op.execute(f"DROP TRIGGER trg_5scr_guard_c3_shadow_issuance_insert_v1 ON {ISSUANCE}")
    op.execute("DROP FUNCTION strategy_5scr_guard_c3_shadow_issuance_insert_v1()")
    op.execute(f"DROP TRIGGER trg_5scr_c3_shadow_issuance_immutable_v1 ON {ISSUANCE}")
    op.execute("DROP FUNCTION strategy_5scr_reject_c3_shadow_issuance_mutation_v1()")
    op.execute("DROP TRIGGER trg_5scr_guard_shadow_projection_command_v1 ON execution_commands")
    op.execute("DROP FUNCTION strategy_5scr_guard_shadow_projection_command_v1()")
    op.drop_table(ISSUANCE)
    op.drop_constraint("ck_execution_command_shadow_projection_v1", "execution_commands", type_="check")
    op.drop_index("uq_execution_command_operator_run_v1", table_name="execution_commands")
    op.drop_index("uq_execution_command_shadow_projection_v1", table_name="execution_commands")
    op.drop_constraint("fk_execution_command_shadow_projection_v1", "execution_commands", type_="foreignkey")
    op.drop_constraint("uq_5scr_shadow_projection_v1_c3_scope", PROJECTION, type_="unique")
    for column in (
        "order_send_eligible",
        "broker_side_effect_allowed",
        "capital_reserved",
        "execution_authority",
        "source_candidate_revision",
        "source_account_snapshot_id",
        "source_candidate_sequence",
        "source_candidate_id",
        "source_shadow_authority_id",
        "operator_run_id",
    ):
        op.drop_column("execution_commands", column)
