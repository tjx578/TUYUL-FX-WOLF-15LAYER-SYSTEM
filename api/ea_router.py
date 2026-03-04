from __future__ import annotations

import contextlib
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
EA_LOG_LIMIT = 200


class RestartRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


class SafeModeRequest(BaseModel):
    enabled: bool
    reason: str = Field(..., min_length=1, max_length=200)


def _append_log(level: str, message: str) -> None:
    row = {
        "id": datetime.now(UTC).strftime("%Y%m%d%H%M%S%f"),
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "message": message,
    }
    with contextlib.suppress(Exception):
        import json

        redis_client.client.lpush(EA_LOGS_KEY, json.dumps(row))
        redis_client.client.ltrim(EA_LOGS_KEY, 0, EA_LOG_LIMIT - 1)


@router.get("/status", dependencies=[Depends(verify_token)])
async def ea_status() -> dict:
    safe_mode = False
    with contextlib.suppress(Exception):
        raw = redis_client.client.get(EA_SAFE_MODE_KEY)
        safe_mode = str(raw or "0").strip().lower() in {"1", "true", "on", "enabled"}

    state = _state_machine.snapshot()
    return {
        "healthy": bool(_ea_manager._running),
        "running": bool(_ea_manager._running),
        "engine_state": state.get("state", "IDLE"),
        "queue_depth": _ea_manager._queue.qsize(),
        "queue_max": _ea_manager._queue.maxsize,
        "safe_mode": safe_mode,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/logs", dependencies=[Depends(verify_token)])
async def ea_logs(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, EA_LOG_LIMIT))
    try:
        import json

        rows = redis_client.client.lrange(EA_LOGS_KEY, 0, limit - 1)
        out: list[dict] = []
        for raw in rows:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str):
                out.append(json.loads(raw))
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
