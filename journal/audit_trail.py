"""
Immutable audit trail for all trade actions.

Zone: journal (J1–J4). APPEND-ONLY. No decision authority. No mutation.

Constitutional compliance:
- Journal is write-only / append-only (immutable).
- No decision power — records what happened, never changes outcomes.
- All trade actions (manual + EA) logged through same interface.
- Rejected setups MUST be logged.

Storage: append-only JSONL file + optional PostgreSQL append-only table.
Each entry is cryptographically chained (hash of previous entry) to
detect tampering.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any  # noqa: UP035

logger = logging.getLogger(__name__)


class AuditAction(Enum):
    """Auditable trade/system actions."""
    # Signal lifecycle
    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"

    # L12 verdicts
    VERDICT_EXECUTE = "VERDICT_EXECUTE"
    VERDICT_HOLD = "VERDICT_HOLD"
    VERDICT_NO_TRADE = "VERDICT_NO_TRADE"
    VERDICT_ABORT = "VERDICT_ABORT"

    # Order lifecycle
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_MODIFIED = "ORDER_MODIFIED"

    # Trade lifecycle
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_PARTIAL_CLOSED = "TRADE_PARTIAL_CLOSED"
    TRADE_CLOSED = "TRADE_CLOSED"

    # Risk & violations
    RISK_CHECK_PASSED = "RISK_CHECK_PASSED"
    RISK_CHECK_FAILED = "RISK_CHECK_FAILED"
    PROP_FIRM_VIOLATION = "PROP_FIRM_VIOLATION"
    SYSTEM_VIOLATION = "SYSTEM_VIOLATION"

    # Key management
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_ROTATED = "API_KEY_ROTATED"
    API_KEY_REVOKED = "API_KEY_REVOKED"

    # Session
    WS_SESSION_CREATED = "WS_SESSION_CREATED"
    WS_SESSION_REVOKED = "WS_SESSION_REVOKED"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"


@dataclass(frozen=True)
class AuditEntry:
    """
    A single immutable audit log entry.

    Frozen dataclass — cannot be modified after creation.
    """
    entry_id: str
    timestamp: str                # ISO 8601 UTC
    action: str                   # AuditAction value
    actor: str                    # Who: "ea", "user:john", "system:l12", etc.
    resource: str                 # What: "signal:abc123", "order:xyz", "key:kid_xxx"
    details: dict[str, Any]       # Action-specific payload
    prev_hash: str                # SHA-256 of previous entry (chain integrity)
    entry_hash: str               # SHA-256 of this entry (excluding entry_hash itself)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "actor": self.actor,
            "resource": self.resource,
            "details": self.details,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


def _compute_hash(
    entry_id: str,
    timestamp: str,
    action: str,
    actor: str,
    resource: str,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute SHA-256 hash of an entry's content (excluding the hash itself)."""
    payload = json.dumps({
        "entry_id": entry_id,
        "timestamp": timestamp,
        "action": action,
        "actor": actor,
        "resource": resource,
        "details": details,
        "prev_hash": prev_hash,
    }, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditTrail:
    """
    Append-only, cryptographically chained audit trail.

    No update. No delete. No mutation. Only append.

    Each entry includes a hash of the previous entry, forming a chain.
    Any tampering with historical entries breaks the chain and is detectable
    via verify_integrity().
    """

    GENESIS_HASH = "0" * 64  # Hash of the "zeroth" entry

    def __init__(self, log_path: Path | None = None, db: Any = None) -> None:
        """
        Args:
            log_path: Path to append-only JSONL file. Created if not exists.
            db: Optional SafeDB instance for PostgreSQL persistence.
        """
        self._log_path = log_path
        self._db = db
        self._last_hash: str = self.GENESIS_HASH
        self._entry_count: int = 0

        # Recover chain state from existing log
        if self._log_path and self._log_path.exists():
            self._recover_chain_state()

    def log(
        self,
        action: AuditAction,
        actor: str,
        resource: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Append an audit entry. This is the ONLY write operation.

        Args:
            action: What happened.
            actor: Who did it (e.g., "ea", "user:admin", "system:l12").
            resource: What was affected (e.g., "signal:abc", "order:123").
            details: Additional context (must be JSON-serializable).

        Returns:
            The created AuditEntry (immutable).
        """
        entry_id = f"audit_{uuid.uuid4().hex[:16]}"
        timestamp = datetime.now(UTC).isoformat()
        details = details or {}

        entry_hash = _compute_hash(
            entry_id=entry_id,
            timestamp=timestamp,
            action=action.value,
            actor=actor,
            resource=resource,
            details=details,
            prev_hash=self._last_hash,
        )

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=timestamp,
            action=action.value,
            actor=actor,
            resource=resource,
            details=details,
            prev_hash=self._last_hash,
            entry_hash=entry_hash,
        )

        # Append to file (atomic-ish: write full line)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")
                f.flush()

        self._last_hash = entry_hash
        self._entry_count += 1

        logger.info(
            "AUDIT [%s] actor=%s resource=%s entry_id=%s",
            action.value, actor, resource, entry_id,
        )

        return entry

    async def log_to_db(
        self,
        action: AuditAction,
        actor: str,
        resource: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Append to both file and PostgreSQL (if db is configured).

        The DB table should be created with:
            CREATE TABLE IF NOT EXISTS audit_trail (
                entry_id    VARCHAR(32) PRIMARY KEY,
                timestamp   TIMESTAMPTZ NOT NULL,
                action      VARCHAR(64) NOT NULL,
                actor       VARCHAR(128) NOT NULL,
                resource    VARCHAR(256) NOT NULL,
                details     JSONB NOT NULL DEFAULT '{}',
                prev_hash   CHAR(64) NOT NULL,
                entry_hash  CHAR(64) NOT NULL
            );
            -- No UPDATE or DELETE grants on this table!
            -- REVOKE UPDATE, DELETE ON audit_trail FROM app_user;
        """
        entry = self.log(action, actor, resource, details)

        if self._db:
            await self._db.execute(
                """INSERT INTO audit_trail
                   (entry_id, timestamp, action, actor, resource, details, prev_hash, entry_hash)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)""",
                entry.entry_id,
                entry.timestamp,
                entry.action,
                entry.actor,
                entry.resource,
                json.dumps(entry.details),
                entry.prev_hash,
                entry.entry_hash,
            )

        return entry

    def verify_integrity(self) -> dict[str, Any]:
        """
        Verify the hash chain integrity of the entire log.

        Returns:
            {
                "valid": bool,
                "entries_checked": int,
                "first_bad_entry": Optional[int],  # 0-indexed line number
                "error": Optional[str],
            }
        """
        if not self._log_path or not self._log_path.exists():
            return {"valid": True, "entries_checked": 0, "first_bad_entry": None, "error": None}

        prev_hash = self.GENESIS_HASH
        line_num = 0

        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    return {
                        "valid": False,
                        "entries_checked": line_num,
                        "first_bad_entry": line_num,
                        "error": f"JSON parse error at line {line_num}: {e}",
                    }

                # Verify prev_hash chain
                if data.get("prev_hash") != prev_hash:
                    return {
                        "valid": False,
                        "entries_checked": line_num,
                        "first_bad_entry": line_num,
                        "error": (
                            f"Chain broken at line {line_num}: "
                            f"expected prev_hash={prev_hash[:16]}..., "
                            f"got {data.get('prev_hash', 'MISSING')[:16]}..."
                        ),
                    }

                # Verify entry_hash
                computed = _compute_hash(
                    entry_id=data["entry_id"],
                    timestamp=data["timestamp"],
                    action=data["action"],
                    actor=data["actor"],
                    resource=data["resource"],
                    details=data["details"],
                    prev_hash=data["prev_hash"],
                )
                if computed != data.get("entry_hash"):
                    return {
                        "valid": False,
                        "entries_checked": line_num,
                        "first_bad_entry": line_num,
                        "error": (
                            f"Hash mismatch at line {line_num}: "
                            f"computed={computed[:16]}..., "
                            f"stored={data.get('entry_hash', 'MISSING')[:16]}..."
                        ),
                    }

                prev_hash = data["entry_hash"]
                line_num += 1

        return {
            "valid": True,
            "entries_checked": line_num,
            "first_bad_entry": None,
            "error": None,
        }

    def _recover_chain_state(self) -> None:
        """Recover last hash from existing log file."""
        if not self._log_path or not self._log_path.exists():
            return

        last_line = ""
        count = 0
        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
                    count += 1

        if last_line:
            try:
                data = json.loads(last_line)
                self._last_hash = data["entry_hash"]
                self._entry_count = count
                logger.info(
                    "Audit trail recovered: %d entries, last_hash=%s...",
                    count, self._last_hash[:16],
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("Failed to recover audit chain state: %s", e)

    @property
    def entry_count(self) -> int:
        return self._entry_count
