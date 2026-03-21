"""Compatibility shim for the legacy EA bridge router.

.. deprecated::
    This module is a **compatibility shim** — sunset 2026-06-01.
    All endpoints delegate to the Agent Manager service where available
    and fall back to the legacy Redis-based implementation when the
    Agent Manager is unavailable (graceful degradation).

    Use `/api/v1/agent-manager/*` endpoints instead.
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from execution.ea_manager import EAManager
from execution.state_machine import ExecutionStateMachine
from journal.audit_trail import AuditAction, AuditTrail
from storage.redis_client import redis_client

from .middleware.auth import verify_token
from .middleware.governance import enforce_write_policy

logger = logging.getLogger(__name__)

# Deprecation constants
_DEPRECATION_SUNSET = "2026-06-01"
_DEPRECATION_REPLACEMENT = "/api/v1/agent-manager"

router = APIRouter(prefix="/api/v1/ea", tags=["ea-bridge"])

_ea_manager = EAManager()
_state_machine = ExecutionStateMachine()
_audit = AuditTrail()

EA_LOGS_KEY = "EA:LOGS"
EA_SAFE_MODE_KEY = "EA:SAFE_MODE"
EA_RESTART_MARKER_KEY = "EA:RESTART_REQUEST"
EA_AGENT_PREFIX = "EA:AGENT:"
EA_LOG_LIMIT = 200

# AgentStatus → legacy status string mapping
_AGENT_STATUS_TO_LEGACY: dict[str, str] = {
    "ONLINE": "connected",
    "WARNING": "degraded",
    "OFFLINE": "disconnected",
    "QUARANTINED": "cooldown",
    "DISABLED": "disconnected",
}


def _deprecation_response(response: Response) -> None:
    """Attach deprecation headers to the response."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = _DEPRECATION_SUNSET
    response.headers["X-Deprecated-Use"] = _DEPRECATION_REPLACEMENT


class RestartRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)
    agent_id: str | None = None


class SafeModeRequest(BaseModel):
    enabled: bool
    reason: str = Field(..., min_length=1, max_length=200)


def _append_log(level: str, message: str, agent_id: str | None = None) -> None:
    row = {
        "id": datetime.now(UTC).strftime("%Y%m%d%H%M%S%f"),
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "message": message,
    }
    if agent_id:
        row["agent_id"] = agent_id
    with contextlib.suppress(Exception):
        redis_client.client.lpush(EA_LOGS_KEY, _json.dumps(row))
        redis_client.client.ltrim(EA_LOGS_KEY, 0, EA_LOG_LIMIT - 1)


def _get_agents() -> list[dict]:
    """Collect per-agent status from Redis EA:AGENT:* hashes."""
    agents: list[dict] = []
    try:
        keys = cast(list[Any], redis_client.client.keys(f"{EA_AGENT_PREFIX}*"))
        for key in keys:
            raw_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            agent_id = raw_key.replace(EA_AGENT_PREFIX, "")
            data = cast(dict[Any, Any], redis_client.client.hgetall(raw_key))
            decoded: dict[str, str] = {}
            for k, v in data.items():
                dk = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                dv = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                decoded[dk] = dv

            agents.append(
                {
                    "agent_id": agent_id,
                    "account_id": decoded.get("account_id", ""),
                    "profile": decoded.get("profile", "default"),
                    "status": decoded.get("status", "disconnected"),
                    "healthy": decoded.get("status", "disconnected") == "connected",
                    "last_heartbeat": decoded.get("last_heartbeat", ""),
                    "last_success": decoded.get("last_success", ""),
                    "last_failure": decoded.get("last_failure", ""),
                    "failure_reason": decoded.get("failure_reason", ""),
                    "trades_executed": int(decoded.get("trades_executed", "0") or "0"),
                    "trades_failed": int(decoded.get("trades_failed", "0") or "0"),
                    "uptime_seconds": int(decoded.get("uptime_seconds", "0") or "0"),
                    "version": decoded.get("version", "unknown"),
                    "scope": decoded.get("scope", "single"),
                }
            )
    except Exception:
        pass

    if not agents:
        # Fallback: synthesize from main EA manager state
        _state_machine.snapshot()
        agents.append(
            {
                "agent_id": "ea-primary",
                "account_id": "",
                "profile": "default",
                "status": "connected" if _ea_manager._running else "disconnected",
                "healthy": bool(_ea_manager._running),
                "last_heartbeat": datetime.now(UTC).isoformat() if _ea_manager._running else "",
                "last_success": "",
                "last_failure": "",
                "failure_reason": "",
                "trades_executed": 0,
                "trades_failed": 0,
                "uptime_seconds": 0,
                "version": "1.0.0",
                "scope": "single",
            }
        )
    return agents


@router.get("/status", dependencies=[Depends(verify_token)])
async def ea_status(request: Request, response: Response) -> dict:
    """Return aggregated EA status.

    .. deprecated::
        Use ``GET /api/v1/agent-manager/agents`` instead. Sunset: 2026-06-01.
        Internally delegates to Agent Manager service; falls back to Redis on failure.
    """
    logger.warning("Deprecated endpoint called: %s", request.url)
    _deprecation_response(response)

    # Try Agent Manager service first (only if it has registered agents)
    try:
        from agents.service import AgentManagerService  # noqa: PLC0415

        svc = AgentManagerService()
        agents_list, total = await svc.list_agents(limit=200)

        if total > 0:
            online_count = sum(1 for a in agents_list if a.get("status") == "ONLINE")
            total_failures = sum(
                a.get("runtime", {}).get("trades_failed", 0) if isinstance(a.get("runtime"), dict) else 0
                for a in agents_list
            )
            safe_mode = any(a.get("safe_mode") for a in agents_list)
            any_locked = any(a.get("locked") for a in agents_list)

            return {
                "healthy": online_count > 0,
                "running": online_count > 0,
                "engine_state": _state_machine.snapshot().get("state", "IDLE"),
                "queue_depth": _ea_manager.queue_snapshot().get("queue_depth", 0),
                "queue_max": _ea_manager.queue_snapshot().get("queue_max", 200),
                "safe_mode": safe_mode,
                "agents_total": total,
                "agents_connected": online_count,
                "total_failures": total_failures,
                "recent_failures": [],
                "cooldown_active": any_locked,
                "updated_at": datetime.now(UTC).isoformat(),
            }
    except Exception:
        pass

    # Graceful degradation: fall back to Redis-based implementation
    safe_mode = False
    with contextlib.suppress(Exception):
        raw = redis_client.client.get(EA_SAFE_MODE_KEY)
        safe_mode = str(raw or "0").strip().lower() in {"1", "true", "on", "enabled"}

    state = _state_machine.snapshot()
    agents = _get_agents()
    queue_info = _ea_manager.queue_snapshot()

    connected_count = sum(1 for a in agents if a.get("healthy"))
    total_failures = sum(a.get("trades_failed", 0) for a in agents)
    recent_failures = [
        {"agent_id": a["agent_id"], "reason": a["failure_reason"], "at": a["last_failure"]}
        for a in agents
        if a.get("last_failure")
    ]

    # Cooldown: check if restart marker is still active
    cooldown_active = False
    with contextlib.suppress(Exception):
        restart_ttl = cast(int | None, redis_client.client.ttl(EA_RESTART_MARKER_KEY))
        if restart_ttl and restart_ttl > 0:
            cooldown_active = True

    return {
        "healthy": bool(_ea_manager._running),
        "running": bool(_ea_manager._running),
        "engine_state": state.get("state", "IDLE"),
        "queue_depth": queue_info.get("queue_depth", 0),
        "queue_max": queue_info.get("queue_max", 200),
        "safe_mode": safe_mode,
        "agents_total": len(agents),
        "agents_connected": connected_count,
        "total_failures": total_failures,
        "recent_failures": recent_failures[-5:],
        "cooldown_active": cooldown_active,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/agents", dependencies=[Depends(verify_token)])
async def ea_agents(request: Request, response: Response) -> list[dict]:
    """Return per-agent / per-EA-instance status in legacy format.

    .. deprecated::
        Use ``GET /api/v1/agent-manager/agents`` instead. Sunset: 2026-06-01.
        Maps Agent Manager ``AgentStatusEnum`` values back to legacy status strings
        (connected/disconnected/degraded/cooldown). Falls back to Redis on failure.
    """
    logger.warning("Deprecated endpoint called: %s", request.url)
    _deprecation_response(response)

    # Try Agent Manager service first (only if it has registered agents)
    try:
        from agents.service import AgentManagerService  # noqa: PLC0415

        svc = AgentManagerService()
        agents_list, total = await svc.list_agents(limit=200)

        if total > 0:
            result: list[dict] = []
            for a in agents_list:
                am_status = str(a.get("status", "OFFLINE"))
                legacy_status = _AGENT_STATUS_TO_LEGACY.get(am_status, "disconnected")
                runtime = a.get("runtime") or {}
                if not isinstance(runtime, dict):
                    runtime = {}
                result.append(
                    {
                        "agent_id": str(a.get("id", "")),
                        "account_id": str(a.get("linked_account_id") or ""),
                        "profile": str(a.get("strategy_profile") or "default"),
                        "status": legacy_status,
                        "healthy": legacy_status == "connected",
                        "last_heartbeat": str(runtime.get("last_heartbeat") or ""),
                        "last_success": str(runtime.get("last_success") or ""),
                        "last_failure": str(runtime.get("last_failure") or ""),
                        "failure_reason": str(runtime.get("failure_reason") or ""),
                        "trades_executed": int(runtime.get("trades_executed") or 0),
                        "trades_failed": int(runtime.get("trades_failed") or 0),
                        "uptime_seconds": int(runtime.get("uptime_seconds") or 0),
                        "version": str(a.get("version") or "unknown"),
                        "scope": str(a.get("ea_class") or "single").lower(),
                    }
                )
            return result
    except Exception:
        pass

    # Graceful degradation: fall back to Redis-based implementation
    return _get_agents()


@router.get("/logs", dependencies=[Depends(verify_token)])
async def ea_logs(request: Request, response: Response, limit: int = 100, agent_id: str | None = None) -> list[dict]:
    """Return EA log entries in legacy format.

    .. deprecated::
        Use ``GET /api/v1/agent-manager/agents/{id}/events`` instead. Sunset: 2026-06-01.
        Maps Agent Manager ``AgentEvent`` records back to legacy log format.
        Falls back to Redis logs on failure.
    """
    logger.warning("Deprecated endpoint called: %s", request.url)
    _deprecation_response(response)

    # Try Agent Manager service first (only if it has registered agents)
    try:
        from agents.service import AgentManagerService  # noqa: PLC0415

        svc = AgentManagerService()
        if agent_id:
            events = await svc.get_agent_events(agent_id, limit=max(1, min(limit, EA_LOG_LIMIT)))
        else:
            # Aggregate events from all agents
            agents_list, total = await svc.list_agents(limit=50)
            if total == 0:
                # No AM agents — skip to Redis fallback
                raise ValueError("no_agents")
            events = []
            per_agent_limit = max(1, limit // max(len(agents_list), 1))
            for a in agents_list:
                try:
                    agent_events = await svc.get_agent_events(
                        str(a["id"]), limit=per_agent_limit
                    )
                    events.extend(agent_events)
                except Exception:
                    continue
            events.sort(key=lambda e: str(e.get("created_at", "")), reverse=True)
            events = events[: max(1, min(limit, EA_LOG_LIMIT))]

        result: list[dict] = []
        for ev in events:
            severity = str(ev.get("severity", "INFO")).upper()
            result.append(
                {
                    "id": str(ev.get("id", "")),
                    "timestamp": str(ev.get("created_at", datetime.now(UTC).isoformat())),
                    "level": severity,
                    "message": str(ev.get("message", "")),
                    "agent_id": str(ev.get("agent_id", "")) or None,
                }
            )
        return result
    except Exception:
        pass

    # Graceful degradation: fall back to Redis-based implementation
    limit = max(1, min(limit, EA_LOG_LIMIT))
    try:
        rows = cast(list[Any], redis_client.client.lrange(EA_LOGS_KEY, 0, limit - 1))
        out: list[dict] = []
        for raw in rows:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str):
                entry = _json.loads(raw)
                if agent_id and entry.get("agent_id") != agent_id:
                    continue
                out.append(entry)
        return out
    except Exception:
        return []


@router.post("/restart", dependencies=[Depends(enforce_write_policy)])
async def restart_ea(req: RestartRequest, request: Request, response: Response) -> dict:
    """Queue an EA restart request.

    .. deprecated::
        Use ``POST /api/v1/agent-manager/agents/{id}/lock`` +
        ``POST /api/v1/agent-manager/agents/{id}/unlock`` instead. Sunset: 2026-06-01.
        Internally calls Agent Manager lock+unlock flow; always also writes Redis marker
        for backward compatibility with legacy consumers.
    """
    logger.warning("Deprecated endpoint called: %s", request.url)
    _deprecation_response(response)
    now = datetime.now(UTC).isoformat()

    # Try Agent Manager service for any registered agents
    try:
        from agents.models import LockAgentRequest as _LockReq  # noqa: PLC0415
        from agents.service import AgentManagerService  # noqa: PLC0415

        svc = AgentManagerService()
        agents_list, total = await svc.list_agents(limit=200)
        if total > 0:
            targets = (
                [a for a in agents_list if str(a.get("id")) == req.agent_id]
                if req.agent_id
                else agents_list
            )
            for a in targets:
                agent_id_str = str(a["id"])
                with contextlib.suppress(Exception):
                    lock_req = _LockReq(reason=req.reason, locked_by="user:dashboard")
                    await svc.lock_agent(agent_id_str, lock_req, performed_by="user:dashboard")
                with contextlib.suppress(Exception):
                    await svc.unlock_agent(agent_id_str, performed_by="user:dashboard")
    except Exception:
        pass

    # Always also write the Redis restart marker for legacy consumers
    with contextlib.suppress(Exception):
        redis_client.client.set(EA_RESTART_MARKER_KEY, now, ex=60 * 10)

    _append_log("WARNING", f"EA restart requested: {req.reason}")
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor="user:dashboard",
        resource="ea:bridge",
        details={"action": "EA_RESTART", "reason": req.reason},
    )
    return {"queued": True, "requested_at": now}


@router.post("/safe-mode", dependencies=[Depends(enforce_write_policy)])
async def set_safe_mode(req: SafeModeRequest, request: Request, response: Response) -> dict:
    """Toggle safe mode for all EA agents.

    .. deprecated::
        Use ``PUT /api/v1/agent-manager/agents/{id}`` with ``safe_mode`` field instead.
        Sunset: 2026-06-01.
        Internally calls Agent Manager updateAgent for each agent; always also writes
        the Redis safe-mode key for backward compatibility with legacy consumers.
    """
    logger.warning("Deprecated endpoint called: %s", request.url)
    _deprecation_response(response)

    # Try Agent Manager service for any registered agents
    try:
        from agents.models import UpdateAgentRequest as _UpdReq  # noqa: PLC0415
        from agents.service import AgentManagerService  # noqa: PLC0415

        svc = AgentManagerService()
        agents_list, total = await svc.list_agents(limit=200)
        if total > 0:
            for a in agents_list:
                agent_id_str = str(a["id"])
                with contextlib.suppress(Exception):
                    upd_req = _UpdReq(safe_mode=req.enabled)
                    await svc.update_agent(agent_id_str, upd_req, performed_by="user:dashboard")
    except Exception:
        pass

    # Always also write the Redis safe-mode key for legacy consumers
    marker = "1" if req.enabled else "0"
    with contextlib.suppress(Exception):
        redis_client.client.set(EA_SAFE_MODE_KEY, marker)

    _append_log("INFO", f"EA safe mode {'enabled' if req.enabled else 'disabled'}: {req.reason}")
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor="user:dashboard",
        resource="ea:bridge",
        details={
            "action": "EA_SAFE_MODE",
            "enabled": req.enabled,
            "reason": req.reason,
        },
    )
    return {
        "safe_mode": req.enabled,
        "reason": req.reason,
        "updated_at": datetime.now(UTC).isoformat(),
    }
