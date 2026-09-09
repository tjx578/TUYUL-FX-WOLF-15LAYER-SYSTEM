"""TEST_ONLY atomic campaign/leg/signal-preview/outbox records."""

from alembic import op

revision = "20260909_06"
down_revision = "20260909_05"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("campaigns", "parent_legs", "signal_previews", "outbox"):
        extra = {
            "campaigns": "UNIQUE(record_id,reservation_id), FOREIGN KEY(tradeplan_id,tradeplan_revision) REFERENCES public.strategy_5scr_candidate_revisions_v31(tradeplan_id,revision), CHECK(record_id=campaign_id)",
            "parent_legs": "UNIQUE(record_id,reservation_id), FOREIGN KEY(campaign_id,reservation_id) REFERENCES public.strategy_5scr_transaction_a_campaigns_v31(record_id,reservation_id), CHECK(record_id=parent_leg_id)",
            "signal_previews": "UNIQUE(record_id,reservation_id), FOREIGN KEY(parent_leg_id,reservation_id) REFERENCES public.strategy_5scr_transaction_a_parent_legs_v31(record_id,reservation_id), CHECK(record_id=signal_id)",
            "outbox": "FOREIGN KEY(signal_id,reservation_id) REFERENCES public.strategy_5scr_transaction_a_signal_previews_v31(record_id,reservation_id), CHECK ((payload::jsonb->>'status'='NON_DELIVERABLE_TEST_ONLY') IS TRUE)",
        }[name]
        op.execute(f"""CREATE TABLE public.strategy_5scr_transaction_a_{name}_v31 (
            record_id uuid PRIMARY KEY, reservation_id uuid NOT NULL UNIQUE,
            account_id text NOT NULL REFERENCES public.strategy_5scr_capacity_ledgers_v31(account_id),
            tradeplan_id uuid NOT NULL, tradeplan_revision integer NOT NULL,
            campaign_id uuid NOT NULL,parent_leg_id uuid NOT NULL,signal_id uuid NOT NULL,
            request_hash text NOT NULL,payload_hash text NOT NULL,payload text NOT NULL,
            CHECK ((payload::jsonb->>'profile'='TEST_ONLY') IS TRUE),
            CHECK ((payload::jsonb->>'execution_authority'='false') IS TRUE),
            CHECK ((payload::jsonb->>'capital_reservation_authority'='false') IS TRUE),
            {extra})""")
    op.execute("""CREATE FUNCTION public.guard_5scr_transaction_a_v31() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected_token uuid;
    BEGIN
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'TRANSACTION_A_RECORD_IMMUTABLE'; END IF;
        SELECT token INTO expected_token FROM public.strategy_5scr_capacity_ledgers_v31 WHERE account_id=NEW.account_id FOR UPDATE;
        IF expected_token IS NULL OR expected_token::text IS DISTINCT FROM current_setting('wolf15.capacity_owner_token',true)
        THEN RAISE EXCEPTION 'TRANSACTION_A_OWNER_FENCED'; END IF;
        RETURN NEW;
    END; $$""")
    for name in ("campaigns", "parent_legs", "signal_previews", "outbox"):
        op.execute(f"""CREATE TRIGGER guard_5scr_transaction_a_v31 BEFORE INSERT OR UPDATE OR DELETE
            ON public.strategy_5scr_transaction_a_{name}_v31 FOR EACH ROW EXECUTE FUNCTION public.guard_5scr_transaction_a_v31()""")


def downgrade():
    for name in ("outbox", "signal_previews", "parent_legs", "campaigns"):
        op.execute(f"DROP TABLE public.strategy_5scr_transaction_a_{name}_v31")
    op.execute("DROP FUNCTION public.guard_5scr_transaction_a_v31()")
