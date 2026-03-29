"""Core engine service package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.engine import runner as runner

__all__ = ["runner"]
