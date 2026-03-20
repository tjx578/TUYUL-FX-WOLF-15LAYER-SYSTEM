"""
Centralized Redis key registry for Wolf-15 services (shared via core/).

ALL Redis key patterns used across the system MUST be defined here.
Hardcoding keys in individual modules is prohibited — import from this module.

Key naming convention:  wolf15:{domain}:{resource}[:{symbol}][:{timeframe}]

Migration note: canonical location moved from state/redis_keys.py → core/redis_keys.py.
The state/ copy re-exports from here for backward compatibility.
"""

# ── Namespace prefix ──────────────────────────────────────────────────────────
PREFIX = "wolf15"

# ── Streams (durable, ordered, consumer-group capable) ────────────────────────
WOLF15_TICK_STREAM = f"{PREFIX}:tick"
WOLF15_SIGNAL_STREAM = f"{PREFIX}:signal"


def tick_stream(symbol: str) -> str:
    """Per-symbol tick stream: wolf15:tick:{symbol}."""
    return f"{PREFIX}:tick:{symbol}"


# ── Hash / Latest snapshots ──────────────────────────────────────────────────
WOLF15_RISK_STATE = f"{PREFIX}:risk:state"
WOLF15_REGIME_STATE = f"{PREFIX}:regime:state"


def latest_tick(symbol: str) -> str:
    """Latest tick hash: wolf15:latest_tick:{symbol}."""
    return f"{PREFIX}:latest_tick:{symbol}"


def latest_candle(symbol: str, timeframe: str) -> str:
    """Latest candle hash: wolf15:candle:{symbol}:{timeframe}."""
    return f"{PREFIX}:candle:{symbol}:{timeframe}"


# ── List history (warmup / recovery) ─────────────────────────────────────────


def candle_history(symbol: str, timeframe: str) -> str:
    """Candle history list: wolf15:candle_history:{symbol}:{timeframe}."""
    return f"{PREFIX}:candle_history:{symbol}:{timeframe}"


def candle_history_temp(symbol: str, timeframe: str) -> str:
    """Temp key for atomic seeding: wolf15:candle_history_tmp:{symbol}:{timeframe}."""
    return f"{PREFIX}:candle_history_tmp:{symbol}:{timeframe}"


# ── Heartbeats ────────────────────────────────────────────────────────────────
HEARTBEAT_INGEST = f"{PREFIX}:heartbeat:ingest"
HEARTBEAT_ENGINE = f"{PREFIX}:heartbeat:engine"
ORCHESTRATOR_STATE = f"{PREFIX}:orchestrator:state"


def heartbeat_ingest_symbol(symbol: str) -> str:
    """Per-symbol ingest heartbeat: wolf15:heartbeat:ingest:{symbol}."""
    return f"{PREFIX}:heartbeat:ingest:{symbol}"


# ── Governance / Kill-switch ──────────────────────────────────────────────────
KILL_SWITCH = f"{PREFIX}:system:kill_switch"
SYSTEM_STATE = f"{PREFIX}:system:state"

# ── WS connection timestamp (for warmup grace period) ────────────────────────
WS_CONNECTED_AT = f"{PREFIX}:ws:connected_at"

# ── Account / Context ────────────────────────────────────────────────────────
ACCOUNT_STATE = f"{PREFIX}:account:state"
LATEST_NEWS = f"{PREFIX}:latest_news"

# ── Pub/Sub channel patterns ─────────────────────────────────────────────────
CHANNEL_TICK_UPDATES = "tick_updates"
CHANNEL_NEWS_UPDATES = "news_updates"
CHANNEL_SYSTEM_STATE = "system:state"


def channel_candle(symbol: str, timeframe: str) -> str:
    """Candle pub/sub channel: candle:{symbol}:{timeframe}."""
    return f"candle:{symbol}:{timeframe}"


# ── Max-lengths and caps ─────────────────────────────────────────────────────
TICK_STREAM_MAXLEN = 10_000
CANDLE_HISTORY_MAXLEN = 300
# Housekeeping TTL only — freshness is computed from last_seen_ts field, NOT key expiry.
LATEST_TICK_TTL_SECONDS = 86400  # 24h housekeeping
LATEST_NEWS_TTL_SECONDS = 86400
