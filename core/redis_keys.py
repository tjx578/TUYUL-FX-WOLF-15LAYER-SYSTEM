"""
Centralized Redis key registry for Wolf-15 services (shared via core/).

ALL Redis key patterns used across the system MUST be defined here.
Hardcoding keys in individual modules is prohibited — import from this module.

Key naming convention:  wolf15:{domain}:{resource}[:{symbol}][:{timeframe}]

Migration note: canonical location moved from state/redis_keys.py → core/redis_keys.py.
The state/ copy re-exports from here for backward compatibility.
"""

from __future__ import annotations

# ── Namespace prefix ──────────────────────────────────────────────────────────
PREFIX = "wolf15"

# ══════════════════════════════════════════════════════════════════════════════
#  STREAMS (durable, ordered, consumer-group capable)
# ══════════════════════════════════════════════════════════════════════════════
WOLF15_TICK_STREAM = f"{PREFIX}:tick"
WOLF15_SIGNAL_STREAM = f"{PREFIX}:signal"


def tick_stream(symbol: str) -> str:
    """Per-symbol tick stream: wolf15:tick:{symbol}. Type: STREAM."""
    return f"{PREFIX}:tick:{symbol}"


# ── Execution streams ────────────────────────────────────────────────────────
TAKE_SIGNAL_EVENTS = f"{PREFIX}:take_signal:events"
EXECUTION_TRUTH = f"{PREFIX}:execution:truth"
EXECUTION_INTENTS = f"{PREFIX}:execution:intents"
RECONCILIATION_EVENTS = f"{PREFIX}:reconciliation:events"

# ── Orchestration streams ────────────────────────────────────────────────────
ORCHESTRATION_EVENTS = f"{PREFIX}:orchestration:events"

# ── Compliance streams ───────────────────────────────────────────────────────
COMPLIANCE_EVENTS = f"{PREFIX}:compliance:events"
COMPLIANCE_AUTO_MODE = f"{PREFIX}:compliance:auto_mode"

# ── Firewall streams ─────────────────────────────────────────────────────────
FIREWALL_EVENTS = f"{PREFIX}:firewall:events"

# ══════════════════════════════════════════════════════════════════════════════
#  HASH / Latest snapshots
# ══════════════════════════════════════════════════════════════════════════════
WOLF15_RISK_STATE = f"{PREFIX}:risk:state"
WOLF15_REGIME_STATE = f"{PREFIX}:regime:state"


def latest_tick(symbol: str) -> str:
    """Latest tick hash: wolf15:latest_tick:{symbol}. Type: HASH, TTL=24h."""
    return f"{PREFIX}:latest_tick:{symbol}"


def latest_candle(symbol: str, timeframe: str) -> str:
    """Latest candle hash: wolf15:candle:{symbol}:{timeframe}. Type: HASH."""
    return f"{PREFIX}:candle:{symbol}:{timeframe}"


# ══════════════════════════════════════════════════════════════════════════════
#  LIST history (warmup / recovery)
# ══════════════════════════════════════════════════════════════════════════════

# Prefix constants for SCAN-based discovery (e.g. redis_consumer, health routes)
CANDLE_HISTORY_PREFIX = f"{PREFIX}:candle_history"
CANDLE_HASH_PREFIX = f"{PREFIX}:candle"


def candle_history(symbol: str, timeframe: str) -> str:
    """Candle history list: wolf15:candle_history:{symbol}:{timeframe}. Type: LIST, max=300."""
    return f"{PREFIX}:candle_history:{symbol}:{timeframe}"


def candle_history_temp(symbol: str, timeframe: str) -> str:
    """Temp key for atomic seeding: wolf15:candle_history_tmp:{symbol}:{timeframe}."""
    return f"{PREFIX}:candle_history_tmp:{symbol}:{timeframe}"


# ── SCAN patterns for candle discovery ───────────────────────────────────────
CANDLE_HISTORY_SCAN = f"{PREFIX}:candle_history:*"
CANDLE_HASH_SCAN = f"{PREFIX}:candle:*"

# ══════════════════════════════════════════════════════════════════════════════
#  HEARTBEATS
# ══════════════════════════════════════════════════════════════════════════════
HEARTBEAT_INGEST = f"{PREFIX}:heartbeat:ingest"
HEARTBEAT_ENGINE = f"{PREFIX}:heartbeat:engine"
ORCHESTRATOR_STATE = f"{PREFIX}:orchestrator:state"


def heartbeat_ingest_symbol(symbol: str) -> str:
    """Per-symbol ingest heartbeat: wolf15:heartbeat:ingest:{symbol}."""
    return f"{PREFIX}:heartbeat:ingest:{symbol}"


# ══════════════════════════════════════════════════════════════════════════════
#  GOVERNANCE / Kill-switch
# ══════════════════════════════════════════════════════════════════════════════
KILL_SWITCH = f"{PREFIX}:system:kill_switch"
SYSTEM_STATE = f"{PREFIX}:system:state"

# ── WS connection timestamp (for warmup grace period) ────────────────────────
WS_CONNECTED_AT = f"{PREFIX}:ws:connected_at"

# ══════════════════════════════════════════════════════════════════════════════
#  ACCOUNT / Context
# ══════════════════════════════════════════════════════════════════════════════
ACCOUNT_STATE = f"{PREFIX}:account:state"
LATEST_NEWS = f"{PREFIX}:latest_news"
TRADE_RISK = f"{PREFIX}:trade:risk"


# ══════════════════════════════════════════════════════════════════════════════
#  COMPLIANCE state
# ══════════════════════════════════════════════════════════════════════════════


def compliance_state(account_id: str) -> str:
    """Compliance state cache: wolf15:compliance:state:{account_id}. Type: STRING, TTL=1h."""
    return f"{PREFIX}:compliance:state:{account_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  DRAWDOWN / Risk metrics (persistence_sync)
# ══════════════════════════════════════════════════════════════════════════════
DRAWDOWN_DAILY = f"{PREFIX}:drawdown:daily"
DRAWDOWN_WEEKLY = f"{PREFIX}:drawdown:weekly"
DRAWDOWN_TOTAL = f"{PREFIX}:drawdown:total"
PEAK_EQUITY = f"{PREFIX}:peak_equity"
CIRCUIT_BREAKER_STATE = f"{PREFIX}:circuit_breaker:state"
CIRCUIT_BREAKER_DATA = f"{PREFIX}:circuit_breaker:data"
CONSECUTIVE_LOSSES = f"{PREFIX}:consecutive_losses"
RECOVERY_LAST_HYDRATION = f"{PREFIX}:recovery:last_hydration"

# Trade record key pattern: wolf15:TRADE:{trade_id}
TRADE_KEY_PREFIX = f"{PREFIX}:TRADE"
TRADE_SCAN_PATTERNS = ("TRADE:*", f"{PREFIX}:TRADE:*")


def trade_key(trade_id: str) -> str:
    """Trade record: wolf15:TRADE:{trade_id}. Type: STRING."""
    return f"{PREFIX}:TRADE:{trade_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  RISK sub-module keys
# ══════════════════════════════════════════════════════════════════════════════
RISK_CORRELATION_MAP = f"{PREFIX}:risk:correlation_map"
RISK_CORR_GROUP_EXPOSURE_PREFIX = f"{PREFIX}:risk:corr_group_exposure:"
RISK_TRAILING_DD_PREFIX = f"{PREFIX}:risk:trailing_dd:"
RISK_PROFILE_PREFIX = f"{PREFIX}:risk:profile:"
RISK_OPEN_TRADES_PREFIX = f"{PREFIX}:risk:open_trades:"


def risk_trailing_dd(account_id: str) -> str:
    """Trailing drawdown state: wolf15:risk:trailing_dd:{account_id}."""
    return f"{PREFIX}:risk:trailing_dd:{account_id}"


def risk_profile(account_id: str) -> str:
    """Risk profile cache: wolf15:risk:profile:{account_id}."""
    return f"{PREFIX}:risk:profile:{account_id}"


def risk_open_trades(account_id: str) -> str:
    """Open trades tracker: wolf15:risk:open_trades:{account_id}."""
    return f"{PREFIX}:risk:open_trades:{account_id}"


def risk_corr_group_exposure(group: str) -> str:
    """Correlation group exposure: wolf15:risk:corr_group_exposure:{group}."""
    return f"{PREFIX}:risk:corr_group_exposure:{group}"


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS cache (Monte Carlo)
# ══════════════════════════════════════════════════════════════════════════════
MC_CACHE_PREFIX = f"{PREFIX}:analysis:mc_cache:"
MC_META_KEY = f"{PREFIX}:analysis:mc_meta"

# ══════════════════════════════════════════════════════════════════════════════
#  WORKER output keys (uppercase legacy convention)
# ══════════════════════════════════════════════════════════════════════════════
WORKER_MC_INPUT = "WOLF15:RETURN_MATRIX"
WORKER_MC_RESULT = "WOLF15:WORKER:MONTE_CARLO:LAST_RESULT"
WORKER_BACKTEST_INPUT = "WOLF15:TRADE_RETURNS"
WORKER_BACKTEST_RESULT = "WOLF15:WORKER:BACKTEST:LAST_RESULT"
WORKER_REGIME_INPUT = "WOLF15:REGIME:VR_VALUES"
WORKER_REGIME_RESULT = "WOLF15:WORKER:REGIME_RECALIBRATION:LAST_RESULT"

# Fallback candle cache (uppercase legacy)
CANDLE_CACHE_PREFIX = "WOLF15:CANDLE_CACHE"

# ══════════════════════════════════════════════════════════════════════════════
#  PUB/SUB channels
# ══════════════════════════════════════════════════════════════════════════════
CHANNEL_TICK_UPDATES = "tick_updates"
CHANNEL_NEWS_UPDATES = "news_updates"
CHANNEL_SYSTEM_STATE = "system:state"

# Orchestrator command channel
ORCHESTRATOR_COMMANDS = f"{PREFIX}:orchestrator:commands"

# Cross-instance WS relay prefix
WS_RELAY_PREFIX = f"{PREFIX}:ws:relay:"
WS_CROSS_INSTANCE_PREFIX = WS_RELAY_PREFIX  # alias used by state/pubsub_channels


def ws_relay_channel(manager_name: str) -> str:
    """Cross-instance WS relay: wolf15:ws:relay:{manager_name}."""
    return f"{PREFIX}:ws:relay:{manager_name}"


def channel_candle(symbol: str, timeframe: str) -> str:
    """Candle pub/sub channel: candle:{symbol}:{timeframe}."""
    return f"candle:{symbol}:{timeframe}"


# Pub/Sub event channels
RISK_EVENTS = f"{PREFIX}:risk:events"
SIGNAL_EVENTS = f"{PREFIX}:signal:events"

# ══════════════════════════════════════════════════════════════════════════════
#  MAX-LENGTHS, TTLS & CAPS
# ══════════════════════════════════════════════════════════════════════════════
TICK_STREAM_MAXLEN = 10_000
CANDLE_HISTORY_MAXLEN = 300
# Housekeeping TTL only — freshness is computed from last_seen_ts field, NOT key expiry.
LATEST_TICK_TTL_SECONDS = 86400  # 24h housekeeping
LATEST_NEWS_TTL_SECONDS = 86400
WS_CONNECTED_AT_TTL = 3600  # 1h

# ══════════════════════════════════════════════════════════════════════════════
#  CONSUMER GROUPS
# ══════════════════════════════════════════════════════════════════════════════
INGEST_GROUP = f"{PREFIX}:ingest:group"
ENGINE_GROUP = f"{PREFIX}:engine:group"
API_GROUP = f"{PREFIX}:api:group"

# ══════════════════════════════════════════════════════════════════════════════
#  TYPE MAP (for sanitizer / health checks)
# ══════════════════════════════════════════════════════════════════════════════
TYPE_MAP: dict[str, str] = {
    "wolf15:tick:*": "stream",
    "wolf15:latest_tick:*": "hash",
    "wolf15:candle:*": "hash",
    "wolf15:candle_history:*": "list",
    "candle_history:*": "list",
    "wolf15:latest_news": "string",
    "heartbeat:*": "string",
    # Zone A / dual-zone SSOT additions
    "wolf15:candle:forming:*": "hash",
    "wolf15:trq:premove:*": "hash",
    "wolf15:trq:r3d_history:*": "list",
    "wolf15:zone:confluence:*": "hash",
}


def expected_type(key: str) -> str | None:
    """Return expected Redis type for a given key (glob match against TYPE_MAP)."""
    import fnmatch  # noqa: PLC0415

    for pattern, rtype in TYPE_MAP.items():
        if fnmatch.fnmatch(key, pattern):
            return rtype
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  DUAL-ZONE SSOT v5 — Zone A (micro-wave M1/M5/M15) + TRQ pre-move
# ══════════════════════════════════════════════════════════════════════════════

# ── Forming candle bars (ingest writes, dashboard reads) ─────────────────────
CANDLE_FORMING_PREFIX = f"{PREFIX}:candle:forming"


def candle_forming(symbol: str, timeframe: str) -> str:
    """Forming candle bar HASH. Type: HASH, TTL=120s.

    Written by FormingBarPublisher (ingest service) every 500ms (M15) or 1s (H1).
    Read by HybridCandleAggregator (api service) for dashboard display.
    """
    return f"{CANDLE_FORMING_PREFIX}:{symbol.upper()}:{timeframe.upper()}"


def channel_candle_forming(symbol: str, timeframe: str) -> str:
    """PubSub channel for forming bar updates: candle:forming:{symbol}:{timeframe}."""
    return f"candle:forming:{symbol.upper()}:{timeframe.upper()}"


# ── TRQ pre-move signals (engine writes, dashboard reads) ────────────────────
TRQ_PREFIX = f"{PREFIX}:trq"


def trq_premove(symbol: str) -> str:
    """Latest TRQ pre-move snapshot HASH. Type: HASH, TTL=300s."""
    return f"{TRQ_PREFIX}:premove:{symbol.upper()}"


def trq_r3d_history(symbol: str) -> str:
    """TRQ R3D history list. Type: LIST, max=100 entries, TTL=6h."""
    return f"{TRQ_PREFIX}:r3d_history:{symbol.upper()}"


def channel_trq_premove() -> str:
    """Broadcast PubSub channel for TRQ pre-move alerts (all symbols)."""
    return "trq:premove:broadcast"


def channel_trq_premove_symbol(symbol: str) -> str:
    """Per-symbol PubSub channel for TRQ pre-move alerts."""
    return f"trq:premove:{symbol.upper()}"


# ── Zone confluence (engine writes, dashboard reads) ─────────────────────────
def zone_confluence(symbol: str) -> str:
    """Zone A + Zone B confluence snapshot HASH. Type: HASH."""
    return f"{PREFIX}:zone:confluence:{symbol.upper()}"


def channel_confluence(symbol: str) -> str:
    """PubSub channel for zone confluence updates."""
    return f"zone:confluence:{symbol.upper()}"


# ── Dual-zone type map (merged into TYPE_MAP above) ──────────────────────────
DUALZONE_TYPE_MAP: dict[str, str] = {
    "wolf15:candle:forming:*": "hash",
    "wolf15:trq:premove:*": "hash",
    "wolf15:trq:r3d_history:*": "list",
    "wolf15:zone:confluence:*": "hash",
}
