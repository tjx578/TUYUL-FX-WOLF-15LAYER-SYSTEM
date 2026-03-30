"""Ingest service package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.ingest import ingest_worker as ingest_worker

__all__ = ["ingest_worker"]
