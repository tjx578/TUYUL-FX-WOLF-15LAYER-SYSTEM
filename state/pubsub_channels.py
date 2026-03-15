"""Centralized Pub/Sub channels."""

ORCHESTRATOR_COMMANDS = "wolf15:orchestrator:commands"
RISK_EVENTS = "wolf15:risk:events"
SIGNAL_EVENTS = "wolf15:signal:events"

# Cross-instance WS relay: when horizontally scaled, each API instance
# publishes WS broadcasts here so peer instances can relay to their
# local WebSocket clients.  Keyed by manager name for targeted relay.
WS_CROSS_INSTANCE_PREFIX = "wolf15:ws:relay:"
