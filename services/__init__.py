"""Service entrypoint package for distributed deployment.

Sub-packages are lazily imported to avoid circular-import cascades.
Direct imports like ``import services.ingest.ingest_worker`` still work
because Python resolves the sub-package path without needing eager
re-exports in this ``__init__``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # static analysis sees the symbols
    from services import api as api
    from services import engine as engine
    from services import ingest as ingest
    from services import orchestrator as orchestrator
    from services import shared as shared
    from services import trade as trade
    from services import worker as worker

__all__ = [
    "api",
    "engine",
    "ingest",
    "orchestrator",
    "shared",
    "trade",
    "worker",
]


def __getattr__(name: str):
    if name in __all__:
        return importlib.import_module(f"services.{name}")
    raise AttributeError(f"module 'services' has no attribute {name!r}")
