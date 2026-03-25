"""DEPRECATED — import from storage.trade_ledger instead (PR-003).

This shim re-exports TradeLedger for backward compatibility.
Will be removed after 2026-06-01.
"""

from storage.trade_ledger import TradeLedger

__all__ = ["TradeLedger"]
