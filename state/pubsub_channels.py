"""
Backward-compatibility shim — canonical source is now core/redis_keys.py.

All symbols re-exported so existing `from state.pubsub_channels import …` keeps working.
New code should import from `core.redis_keys` directly.
"""

from core.redis_keys import (  # noqa: F401
    ORCHESTRATOR_COMMANDS,
    RISK_EVENTS,
    SIGNAL_EVENTS,
    WS_CROSS_INSTANCE_PREFIX,
)
