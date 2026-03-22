"""
Settings Governance — P1-8
============================
Versioned, audited, and rollback-safe settings management.

Every settings change creates an immutable audit entry + versioned snapshot.
Rollback creates a new version (not destructive rewrite).
Write operations require `reason`, `changed_by`, and are role-gated.

Zone: API + persistence — no verdict authority, no market logic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

# ── Models ────────────────────────────────────────────────────────────────────


class SettingsSnapshot(BaseModel):
    """Immutable versioned snapshot of a settings domain."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    domain: str = Field(..., description="Settings domain (risk, pairs, prop_firm, etc.)")
    version: int = Field(..., ge=1, description="Monotonically increasing version")
    settings: dict[str, Any] = Field(..., description="Complete settings payload")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SettingsAuditEntry(BaseModel):
    """Immutable audit entry for a settings change."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"saud_{uuid.uuid4().hex[:12]}")
    domain: str
    snapshot_id: str
    version: int
    action: str = Field(..., description="CREATE | UPDATE | ROLLBACK")
    changed_by: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(..., min_length=3, max_length=512)
    change_ticket: str | None = Field(default=None, max_length=128)
    diff_summary: dict[str, Any] | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SettingsWriteRequest(BaseModel):
    """Request to update settings for a domain."""

    model_config = ConfigDict(extra="forbid")

    settings: dict[str, Any] = Field(..., description="New settings payload")
    changed_by: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(..., min_length=3, max_length=512)
    change_ticket: str | None = Field(default=None, max_length=128)


class SettingsRollbackRequest(BaseModel):
    """Request to rollback to a previous settings version."""

    model_config = ConfigDict(extra="forbid")

    target_version: int = Field(..., ge=1, description="Version to rollback to")
    changed_by: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(..., min_length=3, max_length=512)
    change_ticket: str | None = Field(default=None, max_length=128)


class SettingsResponse(BaseModel):
    """API response for settings read/write."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    version: int
    settings: dict[str, Any]
    updated_at: str


# ── Repository ────────────────────────────────────────────────────────────────


class SettingsGovernanceRepository:
    """Versioned settings persistence with immutable audit trail."""

    def __init__(self) -> None:
        # In-memory fallback
        self._snapshots: dict[str, list[dict[str, Any]]] = {}  # domain -> [versions]
        self._audit_log: list[dict[str, Any]] = []

    async def get_current(self, domain: str) -> SettingsSnapshot | None:
        """Get the latest settings version for a domain."""
        # Try PostgreSQL
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if pg_client.is_available:
                row = await pg_client.fetchrow(
                    """
                    SELECT * FROM settings_snapshots
                    WHERE domain = $1
                    ORDER BY version DESC LIMIT 1
                    """,
                    domain,
                )
                if row:
                    data = dict(row)
                    if isinstance(data.get("settings"), str):
                        data["settings"] = json.loads(data["settings"])
                    return SettingsSnapshot.model_validate(data)
        except Exception:
            pass

        # In-memory fallback
        versions = self._snapshots.get(domain, [])
        if versions:
            return SettingsSnapshot.model_validate(versions[-1])
        return None

    async def get_version(self, domain: str, version: int) -> SettingsSnapshot | None:
        """Get a specific version of settings."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if pg_client.is_available:
                row = await pg_client.fetchrow(
                    "SELECT * FROM settings_snapshots WHERE domain = $1 AND version = $2",
                    domain,
                    version,
                )
                if row:
                    data = dict(row)
                    if isinstance(data.get("settings"), str):
                        data["settings"] = json.loads(data["settings"])
                    return SettingsSnapshot.model_validate(data)
        except Exception:
            pass

        versions = self._snapshots.get(domain, [])
        for v in versions:
            if v.get("version") == version:
                return SettingsSnapshot.model_validate(v)
        return None

    async def save_snapshot(
        self,
        domain: str,
        settings: dict[str, Any],
        changed_by: str,
        reason: str,
        action: str = "UPDATE",
        change_ticket: str | None = None,
    ) -> tuple[SettingsSnapshot, SettingsAuditEntry]:
        """Create a new versioned snapshot and audit entry."""
        current = await self.get_current(domain)
        next_version = (current.version + 1) if current else 1

        snapshot = SettingsSnapshot(
            domain=domain,
            version=next_version,
            settings=settings,
        )
        audit = SettingsAuditEntry(
            domain=domain,
            snapshot_id=snapshot.snapshot_id,
            version=next_version,
            action=action,
            changed_by=changed_by,
            reason=reason,
            change_ticket=change_ticket,
            diff_summary=self._compute_diff(current, settings) if current else None,
        )

        # PostgreSQL
        await self._pg_insert_snapshot(snapshot)
        await self._pg_insert_audit(audit)

        # In-memory
        self._snapshots.setdefault(domain, []).append(snapshot.model_dump(mode="json"))
        self._audit_log.append(audit.model_dump(mode="json"))

        logger.info(
            "[SettingsGov] %s domain=%s v%d by=%s reason=%s",
            action,
            domain,
            next_version,
            changed_by,
            reason,
        )
        return snapshot, audit

    async def get_audit_history(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[SettingsAuditEntry]:
        """Get audit history for a domain."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if pg_client.is_available:
                rows = await pg_client.fetch(
                    """
                    SELECT * FROM settings_audit_log
                    WHERE domain = $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    domain,
                    limit,
                )
                return [SettingsAuditEntry.model_validate(dict(r)) for r in rows]
        except Exception:
            pass

        return [SettingsAuditEntry.model_validate(e) for e in reversed(self._audit_log) if e.get("domain") == domain][
            :limit
        ]

    @staticmethod
    def _compute_diff(
        current: SettingsSnapshot,
        new_settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute a summary of changes between current and new settings."""
        old = current.settings
        added = {k: v for k, v in new_settings.items() if k not in old}
        removed = {k: v for k, v in old.items() if k not in new_settings}
        changed = {
            k: {"old": old[k], "new": new_settings[k]} for k in old if k in new_settings and old[k] != new_settings[k]
        }
        return {"added": added, "removed": removed, "changed": changed}

    # ── PostgreSQL ────────────────────────────────────────────────────────────

    async def _pg_insert_snapshot(self, snap: SettingsSnapshot) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                INSERT INTO settings_snapshots (snapshot_id, domain, version, settings, created_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (domain, version) DO NOTHING
                """,
                snap.snapshot_id,
                snap.domain,
                snap.version,
                json.dumps(snap.settings),
                snap.created_at,
            )
        except Exception:
            logger.warning("[SettingsGov] PG snapshot insert failed", exc_info=True)

    async def _pg_insert_audit(self, audit: SettingsAuditEntry) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                INSERT INTO settings_audit_log (
                    audit_id, domain, snapshot_id, version, action,
                    changed_by, reason, change_ticket, diff_summary, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                audit.audit_id,
                audit.domain,
                audit.snapshot_id,
                audit.version,
                audit.action,
                audit.changed_by,
                audit.reason,
                audit.change_ticket,
                json.dumps(audit.diff_summary) if audit.diff_summary else None,
                audit.created_at,
            )
        except Exception:
            logger.warning("[SettingsGov] PG audit insert failed", exc_info=True)

    @staticmethod
    async def ensure_tables() -> None:
        """Create settings governance tables."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    domain      TEXT NOT NULL,
                    version     INTEGER NOT NULL,
                    settings    JSONB NOT NULL,
                    created_at  TEXT NOT NULL,
                    UNIQUE (domain, version)
                )
                """
            )
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_audit_log (
                    audit_id        TEXT PRIMARY KEY,
                    domain          TEXT NOT NULL,
                    snapshot_id     TEXT NOT NULL,
                    version         INTEGER NOT NULL,
                    action          TEXT NOT NULL,
                    changed_by      TEXT NOT NULL,
                    reason          TEXT NOT NULL,
                    change_ticket   TEXT,
                    diff_summary    JSONB,
                    created_at      TEXT NOT NULL
                )
                """
            )
            await pg_client.execute(
                "CREATE INDEX IF NOT EXISTS idx_settings_audit_domain ON settings_audit_log (domain)"
            )
        except Exception:
            logger.warning("[SettingsGov] Table creation failed", exc_info=True)


# ── Service ───────────────────────────────────────────────────────────────────


class SettingsGovernanceService:
    """Service layer for settings governance with audit + rollback."""

    ALLOWED_DOMAINS = frozenset(
        {
            "risk",
            "pairs",
            "prop_firm",
            "constitution",
            "telegram",
            "finnhub",
            "settings",
            "execution",
        }
    )

    def __init__(self, repo: SettingsGovernanceRepository | None = None) -> None:
        self._repo = repo or SettingsGovernanceRepository()

    async def get_settings(self, domain: str) -> SettingsResponse | None:
        self._validate_domain(domain)
        snap = await self._repo.get_current(domain)
        if snap is None:
            return None
        return SettingsResponse(
            domain=snap.domain,
            version=snap.version,
            settings=snap.settings,
            updated_at=snap.created_at,
        )

    async def update_settings(
        self,
        domain: str,
        request: SettingsWriteRequest,
    ) -> SettingsResponse:
        self._validate_domain(domain)
        snapshot, _audit = await self._repo.save_snapshot(
            domain=domain,
            settings=request.settings,
            changed_by=request.changed_by,
            reason=request.reason,
            action="UPDATE",
            change_ticket=request.change_ticket,
        )
        return SettingsResponse(
            domain=snapshot.domain,
            version=snapshot.version,
            settings=snapshot.settings,
            updated_at=snapshot.created_at,
        )

    async def rollback_settings(
        self,
        domain: str,
        request: SettingsRollbackRequest,
    ) -> SettingsResponse:
        self._validate_domain(domain)
        target = await self._repo.get_version(domain, request.target_version)
        if target is None:
            raise ValueError(f"Version {request.target_version} not found for domain '{domain}'")

        snapshot, _audit = await self._repo.save_snapshot(
            domain=domain,
            settings=target.settings,
            changed_by=request.changed_by,
            reason=f"ROLLBACK to v{request.target_version}: {request.reason}",
            action="ROLLBACK",
            change_ticket=request.change_ticket,
        )
        return SettingsResponse(
            domain=snapshot.domain,
            version=snapshot.version,
            settings=snapshot.settings,
            updated_at=snapshot.created_at,
        )

    async def get_audit_history(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[SettingsAuditEntry]:
        self._validate_domain(domain)
        return await self._repo.get_audit_history(domain, limit)

    def _validate_domain(self, domain: str) -> None:
        if domain not in self.ALLOWED_DOMAINS:
            raise ValueError(f"Unknown settings domain: '{domain}'. Allowed: {', '.join(sorted(self.ALLOWED_DOMAINS))}")
