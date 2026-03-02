"""
Allocation Audit — append-only log of all allocation decisions.

Records every AllocationRequest + AllocationResult for compliance.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from allocation.allocation_models import AllocationRequest, AllocationResult


_LOG_DIR = Path("storage") / "allocation_audit"


class AllocationAudit:
    """Write-only allocation audit log. Append-only. No deletion."""

    _lock = Lock()

    def record(self, request: "AllocationRequest", result: "AllocationResult") -> None:
        """Append an allocation decision to the audit log."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": request.request_id,
            "signal_id": request.signal_id,
            "account_ids": request.account_ids,
            "risk_percent": request.risk_percent,
            "status": result.status,
            "approved": result.approved_count,
            "rejected": result.rejected_count,
            "accounts": [r.model_dump() for r in result.account_results],
        }
        self._write(entry)
        self._redis_append(entry)

    def _write(self, entry: dict) -> None:
        with self._lock:
            try:
                _LOG_DIR.mkdir(parents=True, exist_ok=True)
                log_file = _LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
                with open(log_file, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as exc:
                logger.error(f"AllocationAudit: write failed: {exc}")

    def _redis_append(self, entry: dict) -> None:
        try:
            from storage.redis_client import RedisClient  # noqa: PLC0415
            rc = RedisClient()
            rc.xadd("allocation:audit", {"data": json.dumps(entry)}, maxlen=5000)
        except Exception:
            pass
