"""Owner-fenced S03 consumer storage. Explicit migration; no runtime activation."""

from alembic import op

revision = "20260909_03"
down_revision = "20260909_02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE public.strategy_5scr_owner_fences_v1 (
        symbol text PRIMARY KEY, scope_hash text NOT NULL, owner_id text NOT NULL,
        generation bigint NOT NULL CHECK(generation>0), token uuid NOT NULL UNIQUE)""")
    op.execute("""CREATE FUNCTION public.guard_5scr_lifecycle_owner_v1() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_symbol text; expected_token uuid;
    BEGIN
        IF TG_OP = 'UPDATE' AND NEW.symbol IS DISTINCT FROM OLD.symbol THEN
            RAISE EXCEPTION 'LIFECYCLE_SYMBOL_IMMUTABLE';
        END IF;
        IF TG_OP = 'DELETE' THEN target_symbol := OLD.symbol; ELSE target_symbol := NEW.symbol; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('5scr-owner:' || target_symbol,0));
        SELECT token INTO expected_token FROM public.strategy_5scr_owner_fences_v1 WHERE symbol=target_symbol FOR UPDATE;
        IF FOUND AND expected_token::text IS DISTINCT FROM current_setting('wolf15.lifecycle_owner_token',true) THEN
            RAISE EXCEPTION 'STALE_OR_UNBOUND_LIFECYCLE_OWNER';
        END IF;
        IF expected_token IS NOT NULL AND TG_OP = 'UPDATE' THEN
            IF NEW.event_count < OLD.event_count OR NEW.last_event_at < OLD.last_event_at
               OR (NEW.last_event_at = OLD.last_event_at AND NEW.material_state_hash <> OLD.material_state_hash) THEN
                RAISE EXCEPTION 'STALE_LIFECYCLE_REDUCTION_RELOAD_REQUIRED';
            END IF;
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END; $$""")
    op.execute(
        "CREATE TRIGGER guard_5scr_lifecycle_owner_v1 BEFORE INSERT OR UPDATE OR DELETE "
        "ON public.strategy_5scr_analysis_lifecycles_v2 FOR EACH ROW EXECUTE FUNCTION public.guard_5scr_lifecycle_owner_v1()"
    )
    for name, columns in {
        "inbox": "delivery_id text PRIMARY KEY,payload_hash text NOT NULL,payload jsonb NOT NULL",
        "conflicts": "delivery_id text NOT NULL,payload_hash text NOT NULL,payload jsonb NOT NULL,PRIMARY KEY(delivery_id,payload_hash)",
        "consumer_cursors": "scope_hash text NOT NULL,activity_id text NOT NULL,payload jsonb NOT NULL,PRIMARY KEY(scope_hash,activity_id)",
        "mappings": "consumer_scope_id text NOT NULL,scope_hash text NOT NULL,activity_id text NOT NULL,lifecycle_id text NOT NULL REFERENCES public.strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id),payload jsonb NOT NULL,PRIMARY KEY(consumer_scope_id,activity_id)",
        "emissions": "emission_id text PRIMARY KEY,lifecycle_id text NOT NULL REFERENCES public.strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id),payload jsonb NOT NULL",
    }.items():
        op.execute(f"""CREATE TABLE public.strategy_5scr_activity_{name}_v1 ({columns},
            CHECK ((payload->'execution_authority'='false'::jsonb) IS TRUE
              AND (payload->'hypothesis_authority'='false'::jsonb) IS TRUE
              AND (payload->'risk_authority'='false'::jsonb) IS TRUE))""")


def downgrade():
    for name in ("emissions", "mappings", "consumer_cursors", "conflicts", "inbox"):
        op.execute(f"DROP TABLE public.strategy_5scr_activity_{name}_v1")
    op.execute("DROP TRIGGER guard_5scr_lifecycle_owner_v1 ON public.strategy_5scr_analysis_lifecycles_v2")
    op.execute("DROP FUNCTION public.guard_5scr_lifecycle_owner_v1()")
    op.execute("DROP TABLE public.strategy_5scr_owner_fences_v1")
