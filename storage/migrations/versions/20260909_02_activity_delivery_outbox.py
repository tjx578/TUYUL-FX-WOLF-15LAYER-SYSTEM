"""Add producer delivery outbox; no lifecycle consumer activation.

Revision ID: 20260909_02
Revises: 20260909_01
"""

from alembic import op

revision = "20260909_02"
down_revision = "20260909_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.pair_activity_delivery_outbox_v1 (
            delivery_id text PRIMARY KEY,
            ledger_id text NOT NULL,
            scope_hash text NOT NULL,
            activity_id text NOT NULL,
            evaluation_id text NOT NULL,
            snapshot_id text NOT NULL,
            sequence bigint NOT NULL CHECK (sequence > 0),
            previous_delivery_id text,
            payload text NOT NULL,
            payload_hash text NOT NULL,
            envelope jsonb NOT NULL,
            acknowledged boolean NOT NULL DEFAULT false,
            lease_token uuid,
            lease_until timestamptz,
            attempts bigint NOT NULL DEFAULT 0,
            UNIQUE (ledger_id,scope_hash,evaluation_id),
            UNIQUE (ledger_id,scope_hash,activity_id,sequence),
            UNIQUE (ledger_id,scope_hash,activity_id,delivery_id),
            FOREIGN KEY (ledger_id,activity_id,evaluation_id)
                REFERENCES public.pair_activity_evaluations_v31(ledger_id,activity_id,evaluation_id),
            FOREIGN KEY (ledger_id,snapshot_id)
                REFERENCES public.pair_activity_snapshots_v31(ledger_id,snapshot_id),
            FOREIGN KEY (ledger_id,scope_hash,activity_id,previous_delivery_id)
                REFERENCES public.pair_activity_delivery_outbox_v1(ledger_id,scope_hash,activity_id,delivery_id),
            CHECK ((sequence = 1) = (previous_delivery_id IS NULL)),
            CHECK (envelope = payload::jsonb),
            CHECK ((envelope->>'delivery_id' = delivery_id) IS TRUE),
            CHECK ((envelope->'hypothesis_authority' = 'false'::jsonb) IS TRUE
               AND (envelope->'risk_authority' = 'false'::jsonb) IS TRUE
               AND (envelope->'execution_authority' = 'false'::jsonb) IS TRUE)
        )
    """)
    op.execute("""
        CREATE TABLE public.pair_activity_delivery_cursors_v1 (
            ledger_id text NOT NULL REFERENCES public.pair_activity_ledgers_v31(ledger_id),
            scope_hash text NOT NULL,
            activity_id text NOT NULL,
            sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0),
            last_delivery_id text,
            PRIMARY KEY (ledger_id,scope_hash,activity_id),
            CHECK ((sequence = 0) = (last_delivery_id IS NULL)),
            FOREIGN KEY (ledger_id,scope_hash,activity_id,last_delivery_id)
                REFERENCES public.pair_activity_delivery_outbox_v1(ledger_id,scope_hash,activity_id,delivery_id)
        )
    """)
    op.execute(
        "CREATE INDEX ix_activity_delivery_pending_v1 ON public.pair_activity_delivery_outbox_v1 "
        "(ledger_id,scope_hash,activity_id,sequence) WHERE NOT acknowledged"
    )

    op.execute("""
        CREATE FUNCTION public.guard_activity_delivery_payload_v1() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['acknowledged','lease_token','lease_until','attempts'])
                IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['acknowledged','lease_token','lease_until','attempts']) THEN
                RAISE EXCEPTION 'ACTIVITY_DELIVERY_IMMUTABLE_PAYLOAD';
            END IF;
            IF OLD.acknowledged AND NOT NEW.acknowledged THEN
                RAISE EXCEPTION 'ACTIVITY_DELIVERY_ACK_CANNOT_REWIND';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER guard_activity_delivery_payload_v1 BEFORE UPDATE "
        "ON public.pair_activity_delivery_outbox_v1 FOR EACH ROW "
        "EXECUTE FUNCTION public.guard_activity_delivery_payload_v1()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE public.pair_activity_delivery_cursors_v1")
    op.execute("DROP TABLE public.pair_activity_delivery_outbox_v1")
    op.execute("DROP FUNCTION public.guard_activity_delivery_payload_v1()")
