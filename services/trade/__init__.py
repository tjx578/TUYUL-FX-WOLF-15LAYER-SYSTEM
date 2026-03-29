"""Consolidated trade service — allocation + execution in one process."""

from __future__ import annotations

from services.trade import runner as runner

__all__ = ["runner"]
