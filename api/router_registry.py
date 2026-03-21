"""
Router Registry — Single source of truth for all API router mounts.

Each entry is a (import_path, attribute, description) tuple.
The app factory iterates this list to include_router() in order.
This keeps api_server.py lean and makes it trivial to add/remove routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass(frozen=True, slots=True)
class RouterEntry:
    """Declarative descriptor for a mounted router."""

    module: str  # e.g. "api.allocation_router"
    attr: str  # e.g. "write_router"
    description: str  # human-readable comment


# ── Ordered list — controls mount sequence ────────────────────────────────────
ROUTER_ENTRIES: list[RouterEntry] = [
    # Auth session + refresh (must be first — dashboard blocks on /auth/session)
    RouterEntry("api.auth_router", "router", "Auth session + token refresh"),
    # Legacy /auth/session compat (read-only, no JWT required)
    RouterEntry("api.routes.auth_compat", "router", "Auth compat session probe"),
    # Trade write lifecycle (take/skip/confirm/close/active + risk/calculate)
    RouterEntry("api.allocation_router", "write_router", "Trade write lifecycle"),
    # Take-signal operational binding (P1-1)
    RouterEntry("api.take_signal_routes", "router", "Take-signal binding API"),
    # Admin outbox inspect/replay
    RouterEntry("api.outbox_router", "router", "Trade outbox admin endpoints"),
    # L12 verdicts, context, execution state, pairs
    RouterEntry("api.l12_routes", "router", "L12 verdicts / context / execution state"),
    # WebSocket feeds
    RouterEntry("api.ws_routes", "router", "WebSocket feeds"),
    # Trade Desk read endpoints (desk/detail/exposure)
    RouterEntry("api.trades_router", "router", "Trade Desk read endpoints"),
    # Prices, accounts, trade-by-id (read-only dashboard)
    RouterEntry("api.dashboard_routes", "router", "Dashboard read-only routes"),
    # Constitutional health + equity history
    RouterEntry("api.constitutional_routes", "router", "Constitutional health + equity history"),
    # Risk event log + account snapshots
    RouterEntry("api.risk_events_routes", "router", "Risk event log + account snapshots"),
    # Journal search + metrics
    RouterEntry("api.journal_routes", "router", "Journal search + metrics"),
    # Instrument list + regime + sessions
    RouterEntry("api.instrument_routes", "router", "Instrument list + regime + sessions"),
    # Economic calendar + news-lock
    RouterEntry("news.routes.calendar_routes", "router", "Economic calendar + news-lock"),
    # Frozen SignalContract read APIs
    RouterEntry("api.signals_router", "router", "Frozen signal read APIs"),
    # Read-only account APIs
    RouterEntry("api.accounts_router", "router", "Read-only account APIs"),
    # Prop-firm governance status/phase
    RouterEntry("api.prop_router", "router", "Prop-firm governance status/phase"),
    # EA bridge controls (status/restart/logs/safe-mode)
    RouterEntry("api.ea_router", "router", "EA bridge controls"),
    # Agent Manager CRUD + lifecycle (canonical ea_agents table)
    RouterEntry("api.agent_manager_router", "router", "Agent Manager CRUD + lifecycle"),
    # Agent Ingest — MT5 EA → backend heartbeat/status/portfolio
    RouterEntry("api.agent_ingest_router", "router", "Agent Ingest — MT5 EA data ingestion"),
    # Risk evaluation + preview + kill-switch
    RouterEntry("risk.risk_router", "router", "Risk evaluation + preview + kill-switch"),
    # Runtime config profile engine
    RouterEntry("api.config_profile_router", "router", "Runtime config profile engine"),
    # Prometheus scrape endpoint
    RouterEntry("api.metrics_routes", "router", "Prometheus scrape endpoint"),
    # Redis observability + TCP_OVERWINDOW diagnostics
    RouterEntry("api.redis_health_routes", "router", "Redis observability + diagnostics"),
    # Aggregated fleet health (peer probes)
    RouterEntry("api.system_health_routes", "router", "Aggregated fleet health"),
    # Heartbeat status (ingest/engine producer heartbeat ages)
    RouterEntry("api.heartbeat_routes", "router", "Heartbeat status"),
    # Orchestrator governance state (read-only)
    RouterEntry("api.orchestrator_routes", "router", "Orchestrator governance state"),
    # Settings governance (read/write/rollback/audit) — P1-8
    RouterEntry("api.settings_routes", "router", "Settings governance API"),
]


def load_routers() -> list[tuple[APIRouter, str]]:
    """
    Import and return all routers with their descriptions.

    Returns:
        List of (router_instance, description) tuples in mount order.
    """
    result: list[tuple[APIRouter, str]] = []
    for entry in ROUTER_ENTRIES:
        mod = import_module(entry.module)
        router: APIRouter = getattr(mod, entry.attr)
        result.append((router, entry.description))
    return result
