"""Disposable login-role proof, separate from the eleven consumer scenarios."""

import asyncio
import secrets
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import psycopg
import pytest
from psycopg import sql

from scripts.ci.pair_activity_run_evidence import evidence_directory, write_json
from storage.strategy_5scr_activity_consumer import transfer_owner
from tests.integration.test_activity_delivery_consumer_postgres import setup
from tests.integration.test_pair_activity_runtime_postgres import pg_dsn

__all__ = ["pg_dsn"]

TABLES = (
    "strategy_5scr_analysis_lifecycles_v2",
    "strategy_5scr_activity_inbox_v1",
    "strategy_5scr_activity_conflicts_v1",
    "strategy_5scr_activity_consumer_cursors_v1",
    "strategy_5scr_activity_mappings_v1",
    "strategy_5scr_activity_emissions_v1",
)


def test_consumer_login_role_cannot_bypass_lifecycle_fence(pg_dsn):
    # pg_dsn verifies database markers, server address and destructive-test opt-in
    # before setup or the creation of this unique disposable role is possible.
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    role = "s03_app_" + uuid4().hex[:16]
    password = secrets.token_urlsafe(32)
    parsed = urlsplit(pg_dsn)
    host = parsed.hostname
    assert host is not None
    address = f"[{host}]" if ":" in host else host
    app_dsn = urlunsplit(parsed._replace(netloc=f"{quote(role)}:{quote(password)}@{address}:{parsed.port or 5432}"))
    tables = sql.SQL(", ").join(sql.Identifier("public", name) for name in TABLES)
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        try:
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO {}").format(tables, sql.Identifier(role)))
            admin.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.bind_5scr_lifecycle_owner_v1(text,text,text,bigint,uuid) TO {}"
                ).format(sql.Identifier(role))
            )
            db.dsn = app_dsn

            async def run():
                async with db.transaction() as connection:
                    identity = dict(
                        await connection.fetchrow(
                            "SELECT current_user AS effective_user,session_user AS login_user,rolsuper,rolcreatedb,"
                            "rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    )
                assert identity["effective_user"] == identity["login_user"] == role
                assert all(
                    identity[key] is False
                    for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
                )
                payload = wire()[0]["payload"].encode()
                assert (await consumer.consume(payload))[-1] == "COMMITTED"
                assert (await consumer.consume(payload))[-1] == "DUPLICATE_NO_EFFECT"
                forbidden = (
                    "SET session_replication_role = replica",
                    "ALTER TABLE public.strategy_5scr_analysis_lifecycles_v2 DISABLE TRIGGER ALL",
                    "TRUNCATE public.strategy_5scr_analysis_lifecycles_v2 CASCADE",
                    "UPDATE public.alembic_version SET version_num=version_num",
                    "DELETE FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='S03TEST'",
                    "UPDATE public.strategy_5scr_owner_fences_v1 SET token=gen_random_uuid() WHERE symbol='S03TEST'",
                    "SELECT token FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='S03TEST'",
                    "INSERT INTO public.strategy_5scr_owner_fences_v1 SELECT * FROM public.strategy_5scr_owner_fences_v1",
                )
                for statement in forbidden:
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        async with db.transaction() as connection:
                            await connection.execute(statement)
                # A fresh login has no owner token: even permitted DML must
                # pass the shared trigger before changing legacy lifecycle data.
                with pytest.raises(asyncpg.RaiseError, match="STALE_OR_UNBOUND"):
                    async with db.transaction() as connection:
                        await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=connection)
                control = await asyncpg.connect(pg_dsn)
                try:
                    async with control.transaction():
                        await transfer_owner(
                            control,
                            symbol="S03TEST",
                            scope=consumer.scope,
                            expected_generation=consumer.fence.generation,
                        )
                finally:
                    await control.close()
                with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
                    await consumer.consume(payload)
                # Custom GUCs are writable by any session. An old or invented
                # token must still fail the definer trigger after handover.
                for token in (consumer.fence.token, uuid4()):
                    with pytest.raises(asyncpg.RaiseError, match="STALE_OR_UNBOUND"):
                        async with db.transaction() as connection:
                            await connection.execute(
                                "SELECT set_config('wolf15.lifecycle_owner_token',$1,true)", str(token)
                            )
                            await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=connection)
                return identity

            identity = asyncio.run(run())
            directory = evidence_directory()
            if directory is not None:
                write_json(
                    directory[0] / "application-role.json",
                    {
                        "scope": "DISPOSABLE_LOGIN_ROLE_ONLY_NOT_PRODUCTION_GRANTS",
                        "run_id": directory[1],
                        "identity": identity,
                        "granted_tables": list(TABLES),
                        "committed_and_duplicate": True,
                        "forbidden_privilege_cases": 8,
                        "stale_or_forged_direct_guc_cases": 2,
                        "owner_table_privileges": "NONE",
                        "legacy_unfenced_write_rejected": True,
                        "stale_owner_rejected": True,
                        "credential_recorded": False,
                    },
                )
        finally:
            db.dsn = pg_dsn
            admin.execute(
                sql.SQL(
                    "REVOKE ALL ON FUNCTION public.bind_5scr_lifecycle_owner_v1(text,text,text,bigint,uuid) FROM {}"
                ).format(sql.Identifier(role))
            )
            admin.execute(sql.SQL("REVOKE ALL PRIVILEGES ON {} FROM {}").format(tables, sql.Identifier(role)))
            admin.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
