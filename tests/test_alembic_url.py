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
            "postgres://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        # Standard scheme without driver
        (
            "postgresql://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        # Already has +psycopg (v3) — must still normalise (idempotent)
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        # Legacy psycopg2 driver → must be replaced
        (
            "postgresql+psycopg2://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        # asyncpg driver → replaced to sync psycopg for Alembic
        (
            "postgresql+asyncpg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        # postgres:// with query parameters
        (
            "postgres://user:pass@host:5432/db?sslmode=require",
            "postgresql+psycopg://user:pass@host:5432/db?sslmode=require",
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
    import sys

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
