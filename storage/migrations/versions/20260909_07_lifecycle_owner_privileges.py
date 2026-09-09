"""Separate lifecycle writer capability validation from controller table access.

Deployment must grant EXECUTE on the binder explicitly to its application role,
and must not grant that role SELECT or DML on owner_fences. Existing named-role
grants are not silently changed. Unregistered symbols retain legacy compatibility.
"""

from alembic import op

revision = "20260909_07"
down_revision = "20260909_06"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("REVOKE ALL ON public.strategy_5scr_owner_fences_v1 FROM PUBLIC")
    op.execute("""CREATE FUNCTION public.bind_5scr_lifecycle_owner_v1(
        supplied_symbol text, supplied_scope text, supplied_owner text,
        supplied_generation bigint, supplied_token uuid) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE bound boolean;
    BEGIN
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('5scr-owner:' || supplied_symbol,0));
        SELECT scope_hash = supplied_scope AND owner_id = supplied_owner
            AND generation = supplied_generation AND token = supplied_token INTO bound
            FROM public.strategy_5scr_owner_fences_v1 WHERE symbol = supplied_symbol FOR UPDATE;
        IF bound IS DISTINCT FROM true THEN RETURN false; END IF;
        PERFORM pg_catalog.set_config('wolf15.lifecycle_owner_token',supplied_token::text,true);
        RETURN true;
    END; $$""")
    op.execute("REVOKE ALL ON FUNCTION public.bind_5scr_lifecycle_owner_v1(text,text,text,bigint,uuid) FROM PUBLIC")
    op.execute("ALTER FUNCTION public.guard_5scr_lifecycle_owner_v1() SECURITY DEFINER")
    op.execute("ALTER FUNCTION public.guard_5scr_lifecycle_owner_v1() SET search_path = pg_catalog, pg_temp")
    op.execute("REVOKE ALL ON FUNCTION public.guard_5scr_lifecycle_owner_v1() FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION public.bind_5scr_lifecycle_owner_v1(text,text,text,bigint,uuid)")
    op.execute("ALTER FUNCTION public.guard_5scr_lifecycle_owner_v1() SECURITY INVOKER")
    op.execute("ALTER FUNCTION public.guard_5scr_lifecycle_owner_v1() RESET search_path")
