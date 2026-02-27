"""Alembic environment configuration."""

from __future__ import annotations

import os

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow DATABASE_URL env var to override alembic.ini value so that CI and
# Docker environments don't need to edit the ini file.
url = os.getenv("DATABASE_URL", "")
if url:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
