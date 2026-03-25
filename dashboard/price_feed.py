"""DEPRECATED — import from storage.price_feed instead (PR-003).

This shim re-exports PriceFeed for backward compatibility.
Will be removed after 2026-06-01.
"""

from storage.price_feed import PriceFeed

__all__ = ["PriceFeed"]
