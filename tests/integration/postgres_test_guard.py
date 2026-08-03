"""Fail-closed provenance guard for destructive PostgreSQL integration tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class DisposablePostgresTarget:
    host: str
    port: int
    database: str


_DISPOSABLE_NAME = re.compile(r"^[a-z0-9_]*(?:test|audit)[a-z0-9_]*$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def require_disposable_postgres_target(dsn: str, *, expected_database: str) -> DisposablePostgresTarget:
    """Reject a DSN unless both operator intent and target identity are local/test-only."""

    if not expected_database or _DISPOSABLE_NAME.fullmatch(expected_database) is None:
        raise ValueError("expected disposable database name must contain test or audit")
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("integration DATABASE_URL must use postgres or postgresql")
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("integration DATABASE_URL must target a loopback PostgreSQL server")
    database = unquote(parsed.path.lstrip("/"))
    if database != expected_database:
        raise ValueError("integration DATABASE_URL database does not match the explicit test guard")
    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise ValueError("integration DATABASE_URL has an invalid port") from exc
    return DisposablePostgresTarget(host=host, port=port, database=database)


async def verify_connected_database(connection: object, *, expected_database: str) -> None:
    """Prove server-side identity after connecting; parsing the DSN alone is insufficient."""

    fetchval = getattr(connection, "fetchval", None)
    if fetchval is None:
        raise TypeError("PostgreSQL connection does not expose fetchval")
    actual = await fetchval("SELECT current_database()")
    if str(actual) != expected_database:
        raise RuntimeError("connected PostgreSQL database differs from the explicit test guard")
