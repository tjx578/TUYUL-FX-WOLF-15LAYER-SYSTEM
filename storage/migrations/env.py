"""Alembic environment configuration.

Uses **psycopg v3** (``psycopg``) as the PostgreSQL driver.
Legacy v2 PostgreSQL drivers are intentionally not used in the container image.
"""

from __future__ import annotations

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = getattr(context, "config", None)

if config is not None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# DATABASE_URL → SQLAlchemy-compatible connection string (psycopg v3)
# ---------------------------------------------------------------------------
# Railway / Heroku often provide ``postgres://`` which SQLAlchemy 2.x rejects.
# Some setups already specify a driver suffix (for example ``+asyncpg``).
# We normalise everything to ``postgresql+psycopg://`` so that SQLAlchemy
# always picks the psycopg **v3** driver.
# ---------------------------------------------------------------------------

_PG_SCHEME_RE = re.compile(
    r"^(?:postgres(?:ql)?(?:\+\w+)?)://",  # postgres[ql][+driver]://
)


def _normalise_pg_url(raw: str) -> str:
    """Return *raw* with the scheme forced to ``postgresql+psycopg``."""
    m = _PG_SCHEME_RE.match(raw)
    if not m:
        return raw  # not a PG URL — leave it alone
    return "postgresql+psycopg://" + raw[m.end() :]


url = os.getenv("DATABASE_URL", "")
if config is not None and url:
    url = _normalise_pg_url(url)
    config.set_main_option("sqlalchemy.url", url)

# target_metadata can be set to a SQLAlchemy MetaData instance for
# auto-generate support.  Left as None because schema is managed via
# explicit migration scripts rather than ORM models.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine; calls to
    context.execute() emit SQL to the output stream.  Useful for generating
    a SQL script to review before applying.
    """
    if config is None:
        raise RuntimeError("Alembic config is unavailable in offline migration mode")

    migration_url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a live database connection."""
    if config is None:
        raise RuntimeError("Alembic config is unavailable in online migration mode")

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
