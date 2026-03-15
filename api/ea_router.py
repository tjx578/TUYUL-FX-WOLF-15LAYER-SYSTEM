from __future__ import annotations

import contextlib
import json as _json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from execution.ea_manager import EAManager
from execution.state_machine import ExecutionStateMachine
from journal.audit_trail import AuditAction, AuditTrail
from storage.redis_client import redis_client

router = APIRouter(prefix="/api/v1/ea", tags=["ea-bridge"])

_ea_manager = EAManager()
_state_machine = ExecutionStateMachine()
_audit = AuditTrail()

EA_LOGS_KEY = "EA:LOGS"
EA_SAFE_MODE_KEY = "EA:SAFE_MODE"
EA_RESTART_MARKER_KEY = "EA:RESTART_REQUEST"
EA_AGENT_PREFIX = "EA:AGENT:"
EA_LOG_LIMIT = 200


class RestartRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


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
        keys = redis_client.client.keys(f"{EA_AGENT_PREFIX}*")
        for key in keys:
            raw_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            agent_id = raw_key.replace(EA_AGENT_PREFIX, "")
            data = redis_client.client.hgetall(raw_key)
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
        state = _state_machine.snapshot()
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
async def ea_status() -> dict:
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
    cooldown_until: str | None = None
    with contextlib.suppress(Exception):
        restart_ttl = redis_client.client.ttl(EA_RESTART_MARKER_KEY)
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
async def ea_agents() -> list[dict]:
    """Return per-agent / per-EA-instance status."""
    return _get_agents()


@router.get("/logs", dependencies=[Depends(verify_token)])
async def ea_logs(limit: int = 100, agent_id: str | None = None) -> list[dict]:
    limit = max(1, min(limit, EA_LOG_LIMIT))
    try:
        rows = redis_client.client.lrange(EA_LOGS_KEY, 0, limit - 1)
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
async def restart_ea(req: RestartRequest) -> dict:
    now = datetime.now(UTC).isoformat()
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
async def set_safe_mode(req: SafeModeRequest) -> dict:
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
