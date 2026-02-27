"""
EA (Expert Advisor) executor-status routes.

Mount scope: dashboard/backend/api.py  (standalone dashboard app)
Do NOT add to api_server.py without also updating _assert_no_duplicate_routes() coverage.
EA is an executor only — no market decisions or verdicts live here.

Bridge directory is read from the EA_BRIDGE_DIR environment variable
(default: "bridge" relative to cwd). The bridge uses a file-based protocol —
see ea_interface/mt5_bridge.py for details.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Query

from ea_interface.mt5_bridge import FileBasedMT5Bridge

router = APIRouter(prefix="/api/v1/ea", tags=["ea"])

_BRIDGE_DIR = os.getenv("EA_BRIDGE_DIR", "bridge")


def _bridge() -> FileBasedMT5Bridge:
    """Return a bridge instance pointed at the configured directory."""
    return FileBasedMT5Bridge(Path(_BRIDGE_DIR))


@router.get("/status")
def get_status() -> dict:
    """Return EA bridge health (executor status only — no market state)."""
    return _bridge().health_check()


@router.get("/logs")
def get_logs(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
    """Return the most recent archived EA execution reports (read-only)."""
    archive_dir = Path(_BRIDGE_DIR) / "archive"
    if not archive_dir.exists():
        return []
    files = sorted(
        archive_dir.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    results: list[dict] = []
    for f in files[:limit]:
        try:  # noqa: SIM105
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return results


@router.post("/restart")
def restart() -> dict:
    """Clear pending command files (executor reset only — no market decision)."""
    commands_dir = Path(_BRIDGE_DIR) / "commands"
    cleared = 0
    if commands_dir.exists():
        for f in commands_dir.glob("*.json"):
            try:
                f.unlink()
                cleared += 1
            except Exception:  # noqa: BLE001
                pass
    return {"ok": True, "pending_commands_cleared": cleared}
