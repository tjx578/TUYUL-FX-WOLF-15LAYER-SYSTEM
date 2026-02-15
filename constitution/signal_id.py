"""
Signal ID generator — unique, traceable, sortable.
Format: SIG-{SYMBOL_SHORT}-{YYYYMMDD}-{HHMMSS}-{4RANDOM}
Example: SIG-EU-20260215-143052-A7F2
"""

from __future__ import annotations

import secrets

from datetime import UTC, datetime


def generate_signal_id(symbol: str) -> str:
    """Generate a unique, human-readable signal ID."""
    now = datetime.now(UTC)
    symbol_short = symbol[:2].upper()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    random_part = secrets.token_hex(2).upper()
    return f"SIG-{symbol_short}-{date_part}-{time_part}-{random_part}"
