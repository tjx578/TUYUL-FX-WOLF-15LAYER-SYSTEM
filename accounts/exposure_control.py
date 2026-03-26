"""Per-account exposure controls.

Zone: accounts — risk authority, no execution logic.
"""

from __future__ import annotations

from loguru import logger

__all__ = ["ExposureControl"]


class ExposureControl:
    """Checks whether a new position respects per-account exposure limits.

    Placeholder implementation — always returns within-limits until
    real exposure tracking is wired to the account ledger.
    """

    def is_within_limits(self, account_id: str, symbol: str) -> bool:
        """Return True if opening a new position on *symbol* is safe for *account_id*."""
        logger.debug("[ExposureControl] stub check for {} / {} — allowing", account_id, symbol)
        return True
