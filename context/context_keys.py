"""
Context Keys Registry
All keys used in LiveContextBus must be defined here.
"""

# =========================
# TICK KEYS
# =========================
TICK = {
    "symbol": "symbol",
    "bid": "bid",
    "ask": "ask",
    "timestamp": "timestamp",
    "source": "source",
}

# =========================
# CANDLE KEYS
# =========================
CANDLE = {
    "symbol": "symbol",
    "timeframe": "timeframe",  # M15 / H1
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "timestamp": "timestamp",
}

# =========================
# NEWS KEYS
# =========================
NEWS = {
    "events": "events",
    "impact": "impact",  # high / medium / low
    "currency": "currency",
    "timestamp": "timestamp",
    "source": "source",
}

# =========================
# META / SYSTEM KEYS
# =========================
META = {
    "last_update": "last_update",
    "provider": "provider",
}
