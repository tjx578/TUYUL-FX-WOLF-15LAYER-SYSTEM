"""Lightweight ordered candle-history List namespaces shared by readers."""

import os

from core.redis_keys import CANDLE_HISTORY_PREFIX

# Default ordered list of prefixes that hold *List* data (safe for LRANGE warmup).
# NOTE: wolf15:candle:{sym}:{tf} is a Hash (HSET by RedisContextBridge)
#       — handled separately via HGETALL as a single-bar fallback.
#
# Override at runtime via env var (comma-separated, first-wins):
#   CANDLE_HISTORY_KEY_PREFIXES=wolf15:candle_history,candle_history
CANDLE_HISTORY_LIST_PREFIXES: list[str] = [
    CANDLE_HISTORY_PREFIX,
    "candle_history",
]


def get_candle_prefixes() -> list[str]:
    """Resolve candle List prefixes at call-time.

    Reading at call-time (not import-time) lets tests override
    ``CANDLE_HISTORY_KEY_PREFIXES`` without reloading the module.
    Falls back to module defaults when the env var is absent, empty, or
    contains only whitespace/commas.
    """
    env_val = os.environ.get("CANDLE_HISTORY_KEY_PREFIXES", "").strip()
    if env_val:
        parsed = [p.strip() for p in env_val.split(",") if p.strip()]
        if parsed:
            return parsed
    return list(CANDLE_HISTORY_LIST_PREFIXES)
