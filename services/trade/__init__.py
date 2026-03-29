"""Consolidated trade service — allocation + execution in one process."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.trade import runner as runner

__all__ = ["runner"]
