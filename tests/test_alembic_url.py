"""Tests for the psycopg-v3 URL normalisation in storage/migrations/env.py."""

from __future__ import annotations

import pytest

# Import the private helper directly so we can unit-test it without
# booting the full Alembic context.
from storage.migrations.env import _normalise_pg_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Railway / Heroku legacy scheme
        (
            "postgres://test_user@localhost:5432/test_db",
            "postgresql+psycopg://test_user@localhost:5432/test_db",
        ),
        # Standard scheme without driver
        (
            "postgresql://test_user@localhost:5432/test_db",
            "postgresql+psycopg://test_user@localhost:5432/test_db",
        ),
        # Already has +psycopg (v3) — must still normalise (idempotent)
        (
            "postgresql+psycopg://test_user@localhost/test_db",
            "postgresql+psycopg://test_user@localhost/test_db",
        ),
        # Legacy psycopg2 driver → must be replaced
        (
            "postgresql+psycopg2://test_user@localhost/test_db",
            "postgresql+psycopg://test_user@localhost/test_db",
        ),
        # asyncpg driver → replaced to sync psycopg for Alembic
        (
            "postgresql+asyncpg://test_user@localhost/test_db",
            "postgresql+psycopg://test_user@localhost/test_db",
        ),
        # postgres:// with query parameters
        (
            "postgres://test_user@localhost:5432/test_db?sslmode=require",
            "postgresql+psycopg://test_user@localhost:5432/test_db?sslmode=require",
        ),
        # Non-PG URL left untouched
        (
            "sqlite:///local.db",
            "sqlite:///local.db",
        ),
        # Empty string
        ("", ""),
    ],
)
def test_normalise_pg_url(raw: str, expected: str) -> None:
    assert _normalise_pg_url(raw) == expected


def test_no_psycopg2_import() -> None:
    """Ensure psycopg2 is never imported by the migrations env module."""
    import importlib

    # Reload to be sure we inspect the latest code
    mod = importlib.import_module("storage.migrations.env")

    source_file = mod.__file__
    assert source_file is not None
    with open(source_file) as f:
        source = f.read()

    assert "import psycopg2" not in source, (
        "storage/migrations/env.py must NOT import psycopg2"
    )
    assert "psycopg2" not in source.split("psycopg2-style", 1)[0], (
        "storage/migrations/env.py must not reference psycopg2 "
        "(except in comments)"
    )
