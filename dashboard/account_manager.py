"""DEPRECATED — import from accounts.account_manager instead (PR-003).

This shim re-exports AccountManager for backward compatibility.
Will be removed after 2026-06-01.
"""

from accounts.account_manager import AccountManager

__all__ = ["AccountManager"]
