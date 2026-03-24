"""Environment access helpers for distributed services."""
from __future__ import annotations

import os


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)
