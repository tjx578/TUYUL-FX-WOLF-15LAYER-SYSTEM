"""Shared type-coercion helpers.

These are safe converters for dynamic payload values (Redis hashes, JSON
dicts, config maps) where the runtime type is uncertain.  Every function
returns the *default* on failure instead of raising.
"""

from __future__ import annotations

import contextlib
from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to ``float``, returning *default* on failure."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return float(value)
    return default


def to_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to ``int``, returning *default* on failure."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return int(float(value))
    return default


def to_bool(value: Any, default: bool = False) -> bool:
    """Coerce *value* to ``bool``, returning *default* on failure."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
