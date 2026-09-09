"""Fenced account capacity state for explicit TEST_ONLY transactions."""

from alembic import op

revision = "20260909_05"
down_revision = "20260909_04"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE public.strategy_5scr_capacity_ledgers_v31 (
        account_id text PRIMARY KEY, executor_id uuid NOT NULL, owner_id text NOT NULL,
        owner_epoch bigint NOT NULL CHECK(owner_epoch>0), token uuid NOT NULL UNIQUE,
        version bigint NOT NULL CHECK(version>=0), initial_hash text NOT NULL,
        ledger_hash text NOT NULL CHECK(ledger_hash ~ '^sha256:[0-9a-f]{64}$'), payload text NOT NULL,
        CHECK ((payload::jsonb->>'profile'='TEST_ONLY') IS TRUE),
        CHECK ((payload::jsonb->>'account_id'=account_id) IS TRUE),
        CHECK ((payload::jsonb->>'executor_id'=executor_id::text) IS TRUE),
        CHECK (((payload::jsonb->>'version')::bigint=version) IS TRUE),
        CHECK (((payload::jsonb->>'owner_epoch')::bigint=owner_epoch) IS TRUE)
    )""")
    op.execute("""CREATE FUNCTION public.guard_5scr_capacity_ledger_v31() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected_token uuid;
    BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'CAPACITY_LEDGER_DELETE_PROHIBITED'; END IF;
        IF TG_OP='INSERT' THEN
            expected_token:=NEW.token;
            IF NEW.version<>0 OR NEW.owner_epoch<>1 THEN RAISE EXCEPTION 'CAPACITY_INITIAL_VERSION_INVALID'; END IF;
        ELSE
            expected_token:=OLD.token;
            IF NEW.account_id<>OLD.account_id OR NEW.executor_id<>OLD.executor_id OR NEW.initial_hash<>OLD.initial_hash
               OR NEW.version<>OLD.version+1 THEN RAISE EXCEPTION 'CAPACITY_STATE_VERSION_INVALID'; END IF;
            IF NEW.owner_epoch=OLD.owner_epoch THEN
                IF NEW.token<>OLD.token OR NEW.owner_id<>OLD.owner_id THEN RAISE EXCEPTION 'CAPACITY_OWNER_INVALID'; END IF;
            ELSIF NEW.owner_epoch=OLD.owner_epoch+1 THEN
                IF NEW.token=OLD.token OR (NEW.payload::jsonb-'owner_epoch'-'version') IS DISTINCT FROM
                    (OLD.payload::jsonb-'owner_epoch'-'version') THEN RAISE EXCEPTION 'CAPACITY_HANDOVER_STATE_CHANGED'; END IF;
            ELSE RAISE EXCEPTION 'CAPACITY_OWNER_EPOCH_INVALID'; END IF;
        END IF;
        IF expected_token::text IS DISTINCT FROM current_setting('wolf15.capacity_owner_token',true)
        THEN RAISE EXCEPTION 'CAPACITY_OWNER_FENCED'; END IF;
        RETURN NEW;
    END; $$""")
    op.execute("""CREATE TRIGGER guard_5scr_capacity_ledger_v31 BEFORE INSERT OR UPDATE OR DELETE
        ON public.strategy_5scr_capacity_ledgers_v31 FOR EACH ROW EXECUTE FUNCTION public.guard_5scr_capacity_ledger_v31()""")


def downgrade():
    op.execute("DROP TABLE public.strategy_5scr_capacity_ledgers_v31")
    op.execute("DROP FUNCTION public.guard_5scr_capacity_ledger_v31()")
