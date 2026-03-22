"""
dashboard/db.py — SQL Injection Guard

Provides safe query validation utilities to prevent SQL injection.
All database calls should use parameterised queries ($1, %s) only.

Authority: Dashboard-layer utility. No market decisions.
"""

from __future__ import annotations

import re
from typing import Any


class SQLInjectionError(ValueError):
    """Raised when a SQL query fails injection-safety validation."""


# Pattern that detects Python string interpolation remnants in queries
_FSTRING_PATTERN = re.compile(r"\{[^}]*\}")
# Detect asyncpg-style placeholders like $1, $2
_ASYNCPG_PLACEHOLDER = re.compile(r"\$\d+")
# Detect psycopg2-style placeholders like %s (positional only)
_PSYCOPG_PLACEHOLDER = re.compile(r"%s")
# Detect named psycopg2 placeholders like %(name)s — NOT ALLOWED (interpolation risk)
_NAMED_PSYCOPG_PLACEHOLDER = re.compile(r"%\([^)]+\)s")


def validate_query(query: str, params: Any = None) -> None:
    """Validate a SQL query for injection safety.

    Rules:
        - Query must not be empty.
        - No f-string/format interpolation remnants ({...}).
        - No named psycopg placeholders %(name)s (use positional only).
        - If params supplied, query must have matching placeholders.
        - If query has placeholders, params must be supplied.
        - Placeholder count must match param count.

    Args:
        query: The SQL query string to validate.
        params: Optional tuple/list of query parameters.

    Raises:
        SQLInjectionError: If the query fails any safety check.
    """
    if not query or not query.strip():
        raise SQLInjectionError("Empty query is not allowed")

    # Reject f-string-style interpolation remnants
    if _FSTRING_PATTERN.search(query):
        raise SQLInjectionError("SQL interpolation detected: use parameterised queries ($1 or %s), not {variable}")

    # Reject named psycopg2 placeholders — these are format-style and unsafe
    if _NAMED_PSYCOPG_PLACEHOLDER.search(query):
        raise SQLInjectionError(
            "SQL interpolation detected: named %(name)s placeholders are forbidden; use positional %s or $N"
        )

    # Count placeholders in query
    asyncpg_matches = _ASYNCPG_PLACEHOLDER.findall(query)
    psycopg_matches = _PSYCOPG_PLACEHOLDER.findall(query)
    placeholder_count = len(asyncpg_matches) + len(psycopg_matches)

    param_count = len(params) if params is not None else 0

    if param_count > 0 and placeholder_count == 0:
        raise SQLInjectionError(
            "SQL injection risk: params supplied but query has no placeholders — "
            "params would be ignored and query executed as-is"
        )

    if placeholder_count > 0 and param_count == 0:
        raise SQLInjectionError("SQL safety: query has placeholders but no params supplied")

    if placeholder_count > 0 and param_count > 0 and placeholder_count != param_count:
        raise SQLInjectionError(
            f"SQL param count mismatch: query has {placeholder_count} placeholder(s) "
            f"but {param_count} param(s) supplied"
        )


def sanitize_identifier(name: str) -> str:
    """Safely quote a SQL identifier (table/column name).

    Only allows identifiers matching [a-zA-Z_][a-zA-Z0-9_]* to prevent
    injection through identifier names.

    Args:
        name: The identifier to sanitize.

    Returns:
        The identifier wrapped in double-quotes: '"name"'.

    Raises:
        ValueError: If the identifier contains unsafe characters.
    """
    if not name:
        raise ValueError("Identifier cannot be empty")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError(f"Invalid SQL identifier '{name}': must match [a-zA-Z_][a-zA-Z0-9_]*")
    return f'"{name}"'
